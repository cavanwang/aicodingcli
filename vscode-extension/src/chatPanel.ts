/**
 * 聊天面板 WebView：侧边栏 UI + 消息转发 + 会话管理。
 */

import * as vscode from "vscode";
import * as path from "path";
import { AgentProcess, AgentMessage } from "./agentProcess";
import * as logger from "./logger";

/** 消息记录，用于历史保持 */
interface ChatMessage {
  text: string;
  className: string;
}

export class ChatPanelProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "aicoding.chatView";
  private _view?: vscode.WebviewView;
  private _agent: AgentProcess;
  private _projectRoot: string;
  /** 当前会话消息历史 */
  private _messages: ChatMessage[] = [];

  constructor(
    private readonly _extensionUri: vscode.Uri,
    projectRoot: string,
  ) {
    this._projectRoot = projectRoot;
    this._agent = new AgentProcess();

    // 监听 Agent 消息，转发到 WebView
    this._agent.on("message", (msg: AgentMessage) => {
      logger.log(`[ChatPanel] Agent → WebView: ${msg.type}`);
      // 保存 Agent 回复到历史
      if (msg.type === "done") {
        this._messages.push({ text: msg.reply, className: "msg-agent" });
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

    webviewView.webview.html = this._getHtml();
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
          // 保存用户消息到历史
          this._messages.push({ text: msg.text, className: "msg-user" });
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
          this._postToWebview({ type: "sessionCleared" });
          break;

        case "closeSession":
          logger.log("[ChatPanel] 关闭会话");
          this._stopAgent();
          this._postToWebview({ type: "sessionClosed" });
          break;
      }
    });
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
   * 确保 Agent 进程正在运行。
   */
  private _ensureAgentRunning(): void {
    if (this._agent.ready) {
      return;
    }

    logger.log("[ChatPanel] 启动 Agent 进程...");

    const config = vscode.workspace.getConfiguration("aicoding");
    const pythonPath = config.get<string>("pythonPath", "python");
    const workspace =
      config.get<string>("projectPath") ||
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      this._projectRoot;

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
  private _getHtml(): string {
    return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
  <script>
    const vscode = acquireVsCodeApi();
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('input');
    const sendBtn = document.getElementById('send-btn');
    const newSessionBtn = document.getElementById('new-session-btn');
    const closeSessionBtn = document.getElementById('close-session-btn');

    // 消息历史（内存中保持）
    let messageHistory = [];

    function addMessage(text, className, saveToHistory = true) {
      const div = document.createElement('div');
      div.className = 'msg ' + className;
      div.textContent = text;

      // 为用户消息和 Agent 回复添加复制按钮
      if (className === 'msg-user' || className === 'msg-agent') {
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.textContent = '📋 复制';
        copyBtn.title = '复制到剪贴板';
        copyBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          navigator.clipboard.writeText(text).then(() => {
            copyBtn.textContent = '✅ 已复制';
            setTimeout(() => { copyBtn.textContent = '📋 复制'; }, 1500);
          });
        });
        div.appendChild(copyBtn);
      }

      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      if (saveToHistory) {
        messageHistory.push({ text, className });
      }
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
          addMessage(msg.reply, 'msg-agent');
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
      }
    });
  </script>
</body>
</html>`;
  }
}
