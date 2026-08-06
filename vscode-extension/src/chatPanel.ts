/**
 * 聊天面板 WebView：侧边栏 UI + 消息转发 + 会话管理。
 */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import { AgentProcess, AgentMessage } from "./agentProcess";
import * as logger from "./logger";

/** 消息记录，用于历史保持 */
interface ChatMessage {
  text: string;
  className: string;
}

/** globalState 键名 */
const HISTORY_KEY = "aicoding.chatHistory";

export class ChatPanelProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "aicoding.chatView";
  private _view?: vscode.WebviewView;
  private _agent: AgentProcess;
  private _projectRoot: string;
  private _globalState: vscode.Memento & { setKeysForSync?(keys: readonly string[]): void };
  /** 当前 Agent 进程的工作目录（用于检测项目切换） */
  private _currentWorkspace = "";
  /** 当前会话消息历史 */
  private _messages: ChatMessage[] = [];

  constructor(
    private readonly _extensionUri: vscode.Uri,
    projectRoot: string,
    globalState: vscode.Memento & { setKeysForSync?(keys: readonly string[]): void },
  ) {
    this._projectRoot = projectRoot;
    this._globalState = globalState;
    // 将 history key 标记为需要跨设备同步
    if (this._globalState.setKeysForSync) {
      this._globalState.setKeysForSync([HISTORY_KEY]);
    }
    // 从 globalState 恢复历史消息
    const saved = this._globalState.get<ChatMessage[]>(HISTORY_KEY, []);
    if (saved && saved.length > 0) {
      this._messages = saved;
      logger.log(`[ChatPanel] 从 globalState 恢复 ${saved.length} 条历史消息`);
    }
    this._agent = new AgentProcess();

    // 监听 Agent 消息，转发到 WebView
    this._agent.on("message", (msg: AgentMessage) => {
      logger.log(`[ChatPanel] Agent → WebView: ${msg.type}`);
      // 保存 Agent 回复到历史，并持久化到 globalState
      if (msg.type === "done") {
        this._messages.push({ text: msg.reply, className: "msg-agent" });
        this._persistMessages();
      }
      this._postToWebview(msg);
    });

    this._agent.on("error", (err: Error) => {
      logger.error(`[ChatPanel] Agent 错误: ${err.message}`);
      this._postToWebview({ type: "error", message: `进程错误: ${err.message}` });
    });

    this._agent.on("close", (code: number | null) => {
      logger.log(`[ChatPanel] Agent 退出: code=${code}`);
      this._postToWebview({ type: "agentClosed", code });
    });
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this._extensionUri, "media"),
      ],
    };

    webviewView.webview.html = this._getHtml(webviewView.webview);
    logger.log("[ChatPanel] WebView 已就绪");

    // 监听 WebView 发来的消息
    webviewView.webview.onDidReceiveMessage((msg) => {
      switch (msg.type) {
        case "webviewReady":
          // WebView 加载完成，恢复历史消息
          logger.log(`[ChatPanel] WebView 就绪，历史消息数: ${this._messages.length}`);
          if (this._messages.length > 0) {
            this._postToWebview({ type: "restoreMessages", messages: this._messages });
          }
          break;

        case "userMessage":
          logger.log(`[ChatPanel] 用户消息: ${msg.text.substring(0, 100)}`);
          // 保存用户消息到历史，并持久化到 globalState
          this._messages.push({ text: msg.text, className: "msg-user" });
          this._persistMessages();
          this._ensureAgentRunning();

          // 获取当前编辑器上下文
          const editor = vscode.window.activeTextEditor;
          const context: { activeFile?: string; selection?: string } = {};
          if (editor) {
            context.activeFile = editor.document.uri.fsPath;
            const sel = editor.document.getText(editor.selection);
            if (sel) {
              context.selection = sel;
            }
          }

          this._agent.chat(msg.text, context);
          break;

        case "newSession":
          logger.log("[ChatPanel] 新建会话");
          this._stopAgent();
          this._messages = [];
          this._persistMessages();
          this._postToWebview({ type: "sessionCleared" });
          break;

        case "closeSession":
          logger.log("[ChatPanel] 关闭会话");
          this._stopAgent();
          this._postToWebview({ type: "sessionClosed" });
          break;

        case "confirmReply":
          logger.log(`[ChatPanel] 记忆确认回复: approved=${msg.approved}`);
          this._agent.sendConfirmReply(msg.approved);
          break;
      }
    });
  }

  /**
   * 持久化消息历史到 globalState（跨会话保留）。
   */
  private _persistMessages(): void {
    this._globalState.update(HISTORY_KEY, this._messages);
    logger.log(`[ChatPanel] 消息已持久化 (${this._messages.length} 条)`);
  }

  /**
   * 停止 Agent 进程。
   */
  private _stopAgent(): void {
    if (this._agent.ready) {
      this._agent.stop();
    }
  }

  /**
   * 重启 Agent 进程（工作区切换时调用，使 WORKSPACE_DIR 重新加载）。
   * 不主动启动，等下次用户发消息时 _ensureAgentRunning 以新目录拉起。
   */
  restartAgent(): void {
    logger.log("[ChatPanel] 重启 Agent（工作目录切换）");
    this._agent.stop();
    this._currentWorkspace = "";
  }

  /**
   * 解析 Python 解释器：显式配置 > agentPath/.venv/bin/python > 裸 python。
   * 裸 python 可能解析到无依赖的系统环境（已踩过的坑），优先探测项目 venv。
   */
  private _resolvePythonPath(): string {
    const config = vscode.workspace.getConfiguration("aicoding");
    const configured = config.get<string>("pythonPath", "");
    if (configured) {
      return configured;
    }
    const venvPython = path.join(this._projectRoot, ".venv", "bin", "python");
    if (fs.existsSync(venvPython)) {
      logger.log(`[ChatPanel] 探测到 venv 解释器: ${venvPython}`);
      return venvPython;
    }
    logger.log("[ChatPanel] 未探测到 venv，回退裸 python（可能缺依赖）");
    return "python";
  }

  /**
   * 确保 Agent 进程正在运行，且工作目录与 VSCode 当前打开的项目一致。
   */
  private _ensureAgentRunning(): void {
    // 工作目录始终取 VSCode 当前打开的项目目录（不再被 projectPath 配置劫持）
    const workspace =
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || this._projectRoot;

    // 工作目录变化 → 重启进程（WORKSPACE_DIR 在启动时加载，无法热切换）
    if (this._agent.ready && this._currentWorkspace !== workspace) {
      logger.log(
        `[ChatPanel] 工作目录变化 ${this._currentWorkspace} → ${workspace}，重启 Agent`,
      );
      this._agent.stop();
    }

    if (this._agent.ready) {
      return;
    }

    logger.log("[ChatPanel] 启动 Agent 进程...");

    const pythonPath = this._resolvePythonPath();
    this._currentWorkspace = workspace;
    this._agent.start(pythonPath, workspace, this._projectRoot);
  }

  /**
   * 向 WebView 发送消息。
   */
  private _postToWebview(msg: object): void {
    this._view?.webview.postMessage(msg);
  }

  /**
   * 生成 WebView HTML。
   */
  private _getHtml(_webview?: vscode.Webview): string {
    // markdown-it 库直接内联进 HTML：CSP 已允许 'unsafe-inline'，
    // 避免 <script src> 加载时 webview URI 的 '+' 被编码为 %2B
    // 导致 CSP 拒绝解析的真实环境 bug
    let mdLib = "";
    try {
      mdLib = fs.readFileSync(
        path.join(this._extensionUri.fsPath, "media", "markdown-it.min.js"),
        "utf8",
      );
    } catch (e) {
      logger.error("[ChatPanel] 加载 markdown-it 失败，回退纯文本渲染:", e);
    }
    return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
  <title>AI Coding Chat</title>
  <style>
    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      margin: 0;
      padding: 8px;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    #toolbar {
      display: flex;
      gap: 6px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--vscode-editorWidget-border);
      margin-bottom: 4px;
    }
    .toolbar-btn {
      background: transparent;
      color: var(--vscode-foreground);
      border: 1px solid var(--vscode-input-border);
      border-radius: 4px;
      padding: 4px 10px;
      cursor: pointer;
      font-size: 0.85em;
    }
    .toolbar-btn:hover {
      background: var(--vscode-button-hoverBackground);
    }
    #messages {
      flex: 1;
      overflow-y: auto;
      padding: 4px 0;
    }
    .msg {
      margin: 6px 0;
      padding: 8px 12px;
      border-radius: 8px;
      max-width: 95%;
      word-wrap: break-word;
      white-space: pre-wrap;
      position: relative;
      padding-bottom: 24px;
    }
    .copy-btn {
      position: absolute;
      right: 6px;
      bottom: 4px;
      background: transparent;
      border: none;
      cursor: pointer;
      font-size: 0.75em;
      color: var(--vscode-descriptionForeground);
      padding: 2px 6px;
      border-radius: 3px;
      opacity: 0.7;
    }
    .copy-btn:hover {
      opacity: 1;
      background: var(--vscode-toolbar-hoverBackground);
    }
    .msg-user {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      margin-left: auto;
    }
    .msg-agent {
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-editorWidget-border);
    }
    .msg-error {
      background: var(--vscode-inputValidation-errorBackground);
      border: 1px solid var(--vscode-inputValidation-errorBorder);
      color: var(--vscode-errorForeground);
    }
    .msg-status {
      text-align: center;
      font-size: 0.85em;
      color: var(--vscode-descriptionForeground);
    }
    /* 流式消息样式 */
    .msg-streaming {
      min-height: 20px;
    }
    .stream-status-area {
      margin-bottom: 8px;
    }
    .stream-status-area .msg-status {
      font-size: 0.85em;
      margin: 2px 0;
    }
    .stream-status-area .msg-status.thinking {
      color: var(--vscode-descriptionForeground);
      font-style: italic;
      animation: pulse 1.5s infinite;
    }
    .stream-status-area .msg-status.tool {
      color: var(--vscode-charts-blue);
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }
    .stream-thinking-area {
      margin-bottom: 8px;
    }
    .stream-thinking-area .thinking-content {
      color: var(--vscode-descriptionForeground);
      font-style: italic;
      font-size: 0.9em;
      border-left: 2px solid var(--vscode-descriptionForeground);
      padding-left: 8px;
      margin: 4px 0;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .stream-text-area {
      white-space: pre-wrap;
      word-break: break-word;
    }
    .stream-todo-area {
      margin-top: 8px;
    }
    /* Todo 列表样式 */
    .todo-list {
      background: var(--vscode-editorWidget-background);
      border: 1px solid var(--vscode-editorWidget-border);
      border-radius: 6px;
      padding: 8px 12px;
    }
    .todo-title {
      font-weight: bold;
      margin-bottom: 6px;
      color: var(--vscode-foreground);
    }
    .todo-item {
      padding: 3px 0;
      font-size: 0.9em;
    }
    .todo-item.done {
      color: var(--vscode-descriptionForeground);
      text-decoration: line-through;
    }
    .todo-item.in_progress {
      color: var(--vscode-charts-blue);
    }
    #input-area {
      display: flex;
      gap: 6px;
      padding-top: 8px;
      border-top: 1px solid var(--vscode-editorWidget-border);
    }
    #input {
      flex: 1;
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border);
      border-radius: 4px;
      padding: 6px 10px;
      font-family: inherit;
      font-size: inherit;
      resize: none;
      min-height: 32px;
      max-height: 120px;
    }
    #send-btn {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      border-radius: 4px;
      padding: 6px 14px;
      cursor: pointer;
    }
    #send-btn:hover {
      background: var(--vscode-button-hoverBackground);
    }
    #send-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    /* Markdown 渲染样式（仅作用于 Agent 消息） */
    .msg-md p { margin: 4px 0; }
    .msg-md h1, .msg-md h2, .msg-md h3, .msg-md h4 {
      margin: 8px 0 4px 0;
      line-height: 1.3;
    }
    .msg-md h1 { font-size: 1.15em; }
    .msg-md h2 { font-size: 1.08em; }
    .msg-md h3, .msg-md h4 { font-size: 1em; }
    .msg-md ul, .msg-md ol { margin: 4px 0; padding-left: 20px; }
    .msg-md li { margin: 2px 0; }
    .msg-md code {
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 0.9em;
      background: var(--vscode-textCodeBlock-background);
      padding: 1px 4px;
      border-radius: 3px;
    }
    .msg-md pre {
      background: var(--vscode-textCodeBlock-background);
      border: 1px solid var(--vscode-editorWidget-border);
      border-radius: 4px;
      padding: 8px 10px;
      overflow-x: auto;
      margin: 6px 0;
    }
    .msg-md pre code {
      background: transparent;
      padding: 0;
      white-space: pre;
    }
    .msg-md blockquote {
      border-left: 3px solid var(--vscode-descriptionForeground);
      margin: 4px 0;
      padding: 2px 8px;
      color: var(--vscode-descriptionForeground);
    }
    .msg-md table {
      border-collapse: collapse;
      margin: 6px 0;
      font-size: 0.92em;
    }
    .msg-md th, .msg-md td {
      border: 1px solid var(--vscode-editorWidget-border);
      padding: 3px 8px;
    }
    .msg-md a {
      color: var(--vscode-textLink-foreground);
      text-decoration: none;
    }
    .msg-md hr {
      border: none;
      border-top: 1px solid var(--vscode-editorWidget-border);
      margin: 8px 0;
    }
    /* 代码块头部：语言标签 + 复制按钮 */
    .code-block { margin: 6px 0; }
    .code-block pre { margin: 0; border-top-left-radius: 0; border-top-right-radius: 0; }
    .code-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--vscode-editorWidget-background);
      border: 1px solid var(--vscode-editorWidget-border);
      border-bottom: none;
      border-radius: 4px 4px 0 0;
      padding: 2px 8px;
      font-size: 0.78em;
      color: var(--vscode-descriptionForeground);
    }
    .code-copy {
      background: transparent;
      border: none;
      cursor: pointer;
      color: var(--vscode-descriptionForeground);
      font-size: 1em;
      padding: 1px 4px;
    }
    .code-copy:hover {
      color: var(--vscode-foreground);
    }
  </style>
</head>
<body>
  <div id="toolbar">
    <button class="toolbar-btn" id="new-session-btn" title="新建会话">＋ 新会话</button>
    <button class="toolbar-btn" id="close-session-btn" title="关闭会话">✕ 关闭</button>
  </div>
  <div id="messages">
    <div class="msg msg-status">🤖 AI Coding 助手已就绪，输入消息开始对话</div>
  </div>
  <div id="input-area">
    <textarea id="input" placeholder="输入消息..." rows="1"></textarea>
    <button id="send-btn">发送</button>
  </div>
  <script>${mdLib}</script>
  <script>
    const vscode = acquireVsCodeApi();

    // Markdown 渲染器（仅 Agent 消息）；库加载失败时回退纯文本
    var md = null;
    if (window.markdownit) {
      md = window.markdownit({ html: false, linkify: true, breaks: true });
    }
    function renderMd(text) {
      if (!md) return escapeHtml(text);
      try { return md.render(text); } catch (e) { return escapeHtml(text); }
    }
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('input');
    const sendBtn = document.getElementById('send-btn');
    const newSessionBtn = document.getElementById('new-session-btn');
    const closeSessionBtn = document.getElementById('close-session-btn');

    // 消息历史（内存中保持）
    let messageHistory = [];

    // 流式消息状态
    var streamingMsgEl = null;
    var statusAreaEl = null;
    var thinkingAreaEl = null;
    var textAreaEl = null;
    var todoAreaEl = null;
    var textContent = '';
    var thinkingContent = '';

    function addMessage(text, className, saveToHistory) {
      var div = document.createElement('div');
      div.className = 'msg ' + className;
      if (className === 'msg-agent') {
        // Agent 消息：Markdown 渲染
        div.classList.add('msg-md');
        div.innerHTML = renderMd(text);
        enhanceCodeBlocks(div);
      } else {
        div.textContent = text;
      }
      if (className === 'msg-user' || className === 'msg-agent') {
        var copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.textContent = '\ud83d\udccb \u590d\u5236';
        copyBtn.title = '\u590d\u5236\u5230\u526a\u8d34\u677f';
        copyBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          navigator.clipboard.writeText(text).then(function() {
            copyBtn.textContent = '\u2705 \u5df2\u590d\u5236';
            setTimeout(function() { copyBtn.textContent = '\ud83d\udccb \u590d\u5236'; }, 1500);
          });
        });
        div.appendChild(copyBtn);
      }
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      if (saveToHistory !== false) {
        messageHistory.push({ text: text, className: className });
      }
    }

    // HTML 转义
    function escapeHtml(str) {
      return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\n/g, '<br>');
    }
    
    // 为渲染出的代码块添加「语言标签 + 复制按钮」头部
    function enhanceCodeBlocks(container) {
      container.querySelectorAll('pre > code').forEach(function(codeEl) {
        var pre = codeEl.parentElement;
        if (pre.parentElement && pre.parentElement.classList.contains('code-block')) return;
        var m = codeEl.className.match(/language-([\\w+#-]+)/);
        var langEl = document.createElement('span');
        langEl.textContent = m ? m[1] : 'code';
        var btn = document.createElement('button');
        btn.className = 'code-copy';
        btn.textContent = '\ud83d\udccb \u590d\u5236';
        btn.addEventListener('click', function() {
          navigator.clipboard.writeText(codeEl.textContent).then(function() {
            btn.textContent = '\u2705 \u5df2\u590d\u5236';
            setTimeout(function() { btn.textContent = '\ud83d\udccb \u590d\u5236'; }, 1500);
          });
        });
        var header = document.createElement('div');
        header.className = 'code-header';
        header.appendChild(langEl);
        header.appendChild(btn);
        var wrapper = document.createElement('div');
        wrapper.className = 'code-block';
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
      });
    }

    // 创建流式消息容器（含子区域）
    function getOrCreateStreamingEl() {
      if (!streamingMsgEl) {
        streamingMsgEl = document.createElement('div');
        streamingMsgEl.className = 'msg msg-agent msg-streaming';
        // 状态区域
        statusAreaEl = document.createElement('div');
        statusAreaEl.className = 'stream-status-area';
        streamingMsgEl.appendChild(statusAreaEl);
        // 思考区域
        thinkingAreaEl = document.createElement('div');
        thinkingAreaEl.className = 'stream-thinking-area';
        streamingMsgEl.appendChild(thinkingAreaEl);
        // 文本区域
        textAreaEl = document.createElement('div');
        textAreaEl.className = 'stream-text-area';
        streamingMsgEl.appendChild(textAreaEl);
        // Todo 区域
        todoAreaEl = document.createElement('div');
        todoAreaEl.className = 'stream-todo-area';
        streamingMsgEl.appendChild(todoAreaEl);
        textContent = '';
        thinkingContent = '';
        messagesEl.appendChild(streamingMsgEl);
      }
      return streamingMsgEl;
    }

    // 更新状态区域
    function setStatus(statusText, statusClass) {
      getOrCreateStreamingEl();
      var statusEl = document.createElement('div');
      statusEl.className = 'msg-status ' + (statusClass || '');
      statusEl.textContent = statusText;
      statusAreaEl.appendChild(statusEl);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return statusEl;
    }

    // 移除最后一个状态元素
    function clearLastStatus() {
      if (statusAreaEl && statusAreaEl.lastChild) {
        statusAreaEl.removeChild(statusAreaEl.lastChild);
      }
    }

    // 追加思考内容
    function appendThinking(content) {
      getOrCreateStreamingEl();
      thinkingContent += content;
      thinkingAreaEl.innerHTML = '<div class="thinking-content">' + escapeHtml(thinkingContent) + '</div>';
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // 追加文本内容（流式增量重渲染 Markdown）
    function appendText(content) {
      getOrCreateStreamingEl();
      textContent += content;
      textAreaEl.classList.add('msg-md');
      textAreaEl.innerHTML = renderMd(textContent);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // 更新 Todo 列表
    function updateTodo(items) {
      if (!items || items.length === 0) return;
      getOrCreateStreamingEl();
      var html = '<div class="todo-list"><div class="todo-title">\ud83d\udccb \u4efb\u52a1\u5217\u8868</div>';
      for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var icon = item.status === 'done' ? '\u2705' : item.status === 'in_progress' ? '\ud83d\udd04' : '\u23f3';
        html += '<div class="todo-item ' + item.status + '">' + icon + ' ' + escapeHtml(item.content) + '</div>';
      }
      html += '</div>';
      todoAreaEl.innerHTML = html;
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // 完成流式消息
    function finalizeStreaming(finalText) {
      if (streamingMsgEl) {
        // 清除所有子区域，替换为最终 Markdown 渲染结果
        streamingMsgEl.classList.add('msg-md');
        streamingMsgEl.innerHTML = renderMd(finalText);
        enhanceCodeBlocks(streamingMsgEl);
        var copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.textContent = '\ud83d\udccb \u590d\u5236';
        copyBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          navigator.clipboard.writeText(finalText).then(function() {
            copyBtn.textContent = '\u2705 \u5df2\u590d\u5236';
            setTimeout(function() { copyBtn.textContent = '\ud83d\udccb \u590d\u5236'; }, 1500);
          });
        });
        streamingMsgEl.appendChild(copyBtn);
        messageHistory.push({ text: finalText, className: 'msg-agent' });
      }
      streamingMsgEl = null;
      statusAreaEl = null;
      thinkingAreaEl = null;
      textAreaEl = null;
      todoAreaEl = null;
      textContent = '';
      thinkingContent = '';
    }

    function clearMessages() {
      messagesEl.innerHTML = '';
      messageHistory = [];
    }

    function sendMessage() {
      const text = inputEl.value.trim();
      if (!text) return;
      addMessage(text, 'msg-user');
      vscode.postMessage({ type: 'userMessage', text });
      inputEl.value = '';
      sendBtn.disabled = true;
    }

    // 新建会话
    newSessionBtn.addEventListener('click', () => {
      vscode.postMessage({ type: 'newSession' });
    });

    // 关闭会话
    closeSessionBtn.addEventListener('click', () => {
      vscode.postMessage({ type: 'closeSession' });
    });

    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    // 通知扩展：WebView 已加载完成
    vscode.postMessage({ type: 'webviewReady' });

    // 监听来自扩展的消息
    window.addEventListener('message', (event) => {
      const msg = event.data;
      switch (msg.type) {
        case 'ready':
          addMessage('✅ 已连接 (模型: ' + msg.model + ')', 'msg-status');
          break;
        case 'done':
          // 完成流式消息
          if (streamingMsgEl) {
            finalizeStreaming(msg.reply);
          } else {
            addMessage(msg.reply, 'msg-agent');
          }
          sendBtn.disabled = false;
          break;
        case 'error':
          addMessage('❌ ' + msg.message, 'msg-error');
          sendBtn.disabled = false;
          break;
        case 'pong':
          break;
        case 'agentClosed':
          addMessage('🔌 Agent 已断开 (code=' + msg.code + ')', 'msg-status');
          sendBtn.disabled = false;
          break;
        case 'sessionCleared':
          clearMessages();
          addMessage('🆕 新会话已创建，输入消息开始对话', 'msg-status', false);
          sendBtn.disabled = false;
          break;
        case 'sessionClosed':
          addMessage('🔒 会话已关闭', 'msg-status');
          sendBtn.disabled = true;
          break;
        case 'restoreMessages':
          clearMessages();
          for (const m of msg.messages) {
            addMessage(m.text, m.className, false);
          }
          messageHistory = msg.messages;
          break;

        // 流式消息处理
        case 'thinking_start':
          setStatus('\ud83d\udcad \u601d\u8003\u4e2d...', 'thinking');
          break;
        case 'thinking':
          appendThinking(msg.content);
          break;
        case 'thinking_end':
          clearLastStatus();
          break;
        case 'text':
          appendText(msg.content);
          break;
        case 'tool_start':
          setStatus('\ud83d\udd27 \u8c03\u7528\u5de5\u5177: ' + msg.name, 'tool');
          break;
        case 'tool_end':
          clearLastStatus();
          break;
        case 'todo':
          updateTodo(msg.items);
          break;

        case 'memory_confirm':
          // 显示记忆保存确认 UI
          var confirmDiv = document.createElement('div');
          confirmDiv.className = 'msg msg-confirm';
          var confirmHtml = '<div style="margin-bottom:8px">'
            + '<strong>\ud83d\udcdd 即将保存项目记忆</strong><br/>'
            + '<span style="color:var(--vscode-descriptionForeground)">'
            + '章节: ' + msg.section + '<br/>'
            + '内容: ' + msg.content
            + '</span></div>'
            + '<div>'
            + '<button class="confirm-yes" style="margin-right:8px;padding:2px 12px;cursor:pointer;background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:none;border-radius:3px">\u2705 同意保存</button>'
            + '<button class="confirm-no" style="padding:2px 12px;cursor:pointer;background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground);border:none;border-radius:3px">\u274c 拒绝</button>'
            + '</div>';
          confirmDiv.innerHTML = confirmHtml;
          confirmDiv.querySelector('.confirm-yes').addEventListener('click', function() {
            vscode.postMessage({ type: 'confirmReply', approved: true });
            confirmDiv.innerHTML = '<em style="color:var(--vscode-descriptionForeground)">\u2705 已同意保存</em>';
          });
          confirmDiv.querySelector('.confirm-no').addEventListener('click', function() {
            vscode.postMessage({ type: 'confirmReply', approved: false });
            confirmDiv.innerHTML = '<em style="color:var(--vscode-descriptionForeground)">\u274c 已拒绝保存</em>';
          });
          messagesEl.appendChild(confirmDiv);
          messagesEl.scrollTop = messagesEl.scrollHeight;
          break;
      }
    });
  </script>
</body>
</html>`;
  }
}
