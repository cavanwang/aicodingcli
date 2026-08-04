/**
 * 统一日志模块：输出到 VS Code OutputChannel。
 *
 * 用户可在 VS Code 中通过 "输出: AI Coding" 面板查看日志。
 */

import * as vscode from "vscode";

let _channel: vscode.OutputChannel | undefined;

function getChannel(): vscode.OutputChannel {
  if (!_channel) {
    _channel = vscode.window.createOutputChannel("AI Coding");
  }
  return _channel;
}

function timestamp(): string {
  return new Date().toISOString().replace("T", " ").substring(0, 19);
}

/** 输出一条普通日志。 */
export function log(message: string, ...args: unknown[]): void {
  const formatted = args.length
    ? `${message} ${args.map((a) => JSON.stringify(a)).join(" ")}`
    : message;
  getChannel().appendLine(`[${timestamp()}] ${formatted}`);
}

/** 输出一条错误日志。 */
export function error(message: string, ...args: unknown[]): void {
  const formatted = args.length
    ? `${message} ${args.map((a) => JSON.stringify(a)).join(" ")}`
    : message;
  getChannel().appendLine(`[${timestamp()}] ERROR: ${formatted}`);
}

/** 销毁 OutputChannel（扩展卸载时调用）。 */
export function dispose(): void {
  _channel?.dispose();
  _channel = undefined;
}
