/**
 * VS Code 扩展入口：注册命令、激活侧边栏。
 */

import * as vscode from "vscode";
import * as path from "path";
import { ChatPanelProvider } from "./chatPanel";
import * as logger from "./logger";

let agentProcess: import("./agentProcess").AgentProcess | undefined;

export function activate(context: vscode.ExtensionContext): void {
  // Agent 安装目录（main.py 所在位置）：agentPath 配置 > 兼容旧 projectPath > 当前打开目录（开发模式） > 扩展父目录
  // 注意：这里只影响定位 main.py，Agent 的工作目录始终取 VSCode 当前打开的项目目录（见 chatPanel）
  const config = vscode.workspace.getConfiguration("aicoding");
  const configuredPath =
    config.get<string>("agentPath", "") || config.get<string>("projectPath", "");
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const devFallback = path.dirname(context.extensionUri.fsPath);
  const projectRoot = configuredPath || workspaceFolder || devFallback;

  // 注册 WebView 侧边栏
  const chatProvider = new ChatPanelProvider(
    context.extensionUri,
    projectRoot,
    context.globalState,
  );

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      ChatPanelProvider.viewType,
      chatProvider,
    ),
  );

  // 工作区目录变化（打开新项目/切换文件夹）时重启 Agent，使 WORKSPACE_DIR 重新加载
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      logger.log("[Extension] 工作区变化，重启 Agent 以切换工作目录");
      chatProvider.restartAgent();
    }),
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
