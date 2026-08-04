/**
 * 聊天面板 WebView：侧边栏 UI + 消息转发。
 */

import * as vscode from "vscode";
import * as path from "path";
import { AgentProcess, AgentMessage } from "./agentProcess";
import * as logger from "./logger";

export class ChatPanelProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "aicoding.chatView";
  private _view?: vscode.WebviewView;
  private _agent: AgentProcess;
  private _projectRoot: string;

  constructor(
    private readonly _extensionUri: vscode.Uri,
    projectRoot: string,
  ) {
    this._projectRoot = projectRoot;
    this._agent = new AgentProcess();

    // 监听 Agent 消息，转发到 WebView
    this._agent.on("message", (msg: AgentMessage) => {
      logger.log(`[ChatPanel] Agent → WebView: ${msg.type}`);
      this._postToWebview(msg);
    });

    this._agent.on("error", (err: Error) => {
      logger.error(`[ChatPanel] Agent 错误: ${err.message}`);
      this._postToWebview({ type: "error", message: `进程错误: ${err.message}` });
    });

    this._agent.on("close", (code: number | null) => {
      logger.log(`[ChatPanel] Agent 退出: code=${code}`);
      this._postToWebview({ type: "error", message: `Agent 已退出 (code=${code})` });
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
      if (msg.type === "userMessage") {
        logger.log(`[ChatPanel] 用户消息: ${msg.text.substring(0, 100)}`);
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
      }
    });
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

    function addMessage(text, className) {
      const div = document.createElement('div');
      div.className = 'msg ' + className;
      div.textContent = text;
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function sendMessage() {
      const text = inputEl.value.trim();
      if (!text) return;
      addMessage(text, 'msg-user');
      vscode.postMessage({ type: 'userMessage', text });
      inputEl.value = '';
      sendBtn.disabled = true;
    }

    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

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
        case 'bye':
          addMessage('👋 Agent 已退出', 'msg-status');
          break;
      }
    });
  </script>
</body>
</html>`;
  }
}
