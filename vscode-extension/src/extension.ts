/**
 * VS Code 扩展入口：注册命令、激活侧边栏。
 */

import * as vscode from "vscode";
import * as path from "path";
import { ChatPanelProvider } from "./chatPanel";
import * as logger from "./logger";

let agentProcess: import("./agentProcess").AgentProcess | undefined;

export function activate(context: vscode.ExtensionContext): void {
  // 解析项目根目录：优先使用配置，其次工作区目录，最后回退到扩展父目录（开发模式）
  const config = vscode.workspace.getConfiguration("aicoding");
  const configuredPath = config.get<string>("projectPath", "");
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const devFallback = path.dirname(context.extensionUri.fsPath);
  const projectRoot = configuredPath || workspaceFolder || devFallback;

  // 注册 WebView 侧边栏
  const chatProvider = new ChatPanelProvider(
    context.extensionUri,
    projectRoot,
  );

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      ChatPanelProvider.viewType,
      chatProvider,
    ),
  );

  // 注册命令
  context.subscriptions.push(
    vscode.commands.registerCommand("aicoding.startChat", () => {
      // 聚焦到侧边栏视图
      vscode.commands.executeCommand("aicoding.chatView.focus");
    }),
  );

  logger.log(`[Extension] 激活: projectRoot=${projectRoot}`);
}

export function deactivate(): void {
  logger.log("[Extension] 卸载");
  if (agentProcess) {
    agentProcess.stop();
    agentProcess = undefined;
  }
  logger.dispose();
}
