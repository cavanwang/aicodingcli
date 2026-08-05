/**
 * Agent 子进程管理：spawn Python --server 进程，通过 JSON Lines 通信。
 */

import { ChildProcess, spawn } from "child_process";
import { EventEmitter } from "events";
import * as logger from "./logger";

/** 从 Python Agent 收到的消息类型 */
export interface AgentReadyMsg {
  type: "ready";
  model: string;
  workspace: string;
}
export interface AgentDoneMsg {
  type: "done";
  reply: string;
}
export interface AgentErrorMsg {
  type: "error";
  message: string;
}
export interface AgentPongMsg {
  type: "pong";
}
export interface AgentByeMsg {
  type: "bye";
}
export type AgentMessage =
  | AgentReadyMsg
  | AgentDoneMsg
  | AgentErrorMsg
  | AgentPongMsg
  | AgentByeMsg;

/**
 * 管理 Python Agent 子进程的生命周期和通信。
 *
 * 事件：
 * - "message": 收到 Agent 消息 (AgentMessage)
 * - "error": 进程出错
 * - "close": 进程退出
 */
export class AgentProcess extends EventEmitter {
  private _child: ChildProcess | null = null;
  private buffer = "";
  private _ready = false;

  get ready(): boolean {
    return this._ready;
  }

  /**
   * 启动 Python Agent 子进程。
   */
  start(pythonPath: string, workspace: string, projectRoot: string): void {
    if (this._child) {
      this.stop();
    }

    const mainPy = projectRoot + "/main.py";
    logger.log(`[AgentProcess] 启动: python=${pythonPath}, workspace=${workspace}`);

    this._child = spawn(pythonPath, [
      mainPy,
      "--server",
      "--workspace",
      workspace,
    ], {
      cwd: projectRoot,
      env: process.env,
    });

    this._child.stdout?.on("data", (data: Buffer) => {
      this.buffer += data.toString();
      this._processBuffer();
    });

    this._child.stderr?.on("data", (data: Buffer) => {
      logger.error("[Agent stderr]", data.toString().trim());
    });

    this._child.on("error", (err: Error) => {
      logger.error("[AgentProcess] 进程错误:", err.message);
      this.emit("error", err);
    });

    this._child.on("close", (code: number | null) => {
      logger.log(`[AgentProcess] 进程退出: code=${code}`);
      this._ready = false;
      this.emit("close", code);
    });
  }

  /**
   * 停止子进程。
   */
  stop(): void {
    if (this._child) {
      logger.log("[AgentProcess] 停止进程");
      const childToStop = this._child;  // 捕获当前子进程引用
      this.send({ type: "quit" });
      setTimeout(() => {
        if (childToStop && !childToStop.killed) {
          childToStop.kill("SIGTERM");
        }
      }, 2000);
      this._child = null;
      this._ready = false;
    }
  }

  /**
   * 发送聊天消息，可附带编辑器上下文。
   */
  chat(message: string, context?: { activeFile?: string; selection?: string }): void {
    logger.log(`[AgentProcess] chat: ${message.substring(0, 100)}`);
    const msg: Record<string, unknown> = { type: "chat", message };
    if (context?.activeFile) {
      msg.activeFile = context.activeFile;
    }
    if (context?.selection) {
      msg.selection = context.selection;
    }
    this.send(msg);
  }

  /**
   * 发送心跳。
   */
  ping(): void {
    this.send({ type: "ping" });
  }

  /**
   * 回复记忆保存确认。
   */
  sendConfirmReply(approved: boolean): void {
    logger.log(`[AgentProcess] confirm_reply: approved=${approved}`);
    this.send({ type: "confirm_reply", approved });
  }

  /**
   * 发送 JSON 消息到子进程 stdin。
   */
  private send(msg: object): void {
    if (!this._child?.stdin?.writable) {
      logger.error("[AgentProcess] 进程未运行，无法发送消息");
      return;
    }
    logger.log(`[AgentProcess] → ${JSON.stringify(msg).substring(0, 200)}`);
    const line = JSON.stringify(msg) + "\n";
    this._child.stdin.write(line);
  }

  /**
   * 处理 stdout 缓冲区，按行解析 JSON。
   */
  private _processBuffer(): void {
    const lines = this.buffer.split("\n");
    // 最后一行可能不完整，保留在 buffer
    this.buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      try {
        const msg: AgentMessage = JSON.parse(trimmed);
        logger.log(`[AgentProcess] ← ${msg.type}`);
        if (msg.type === "ready") {
          this._ready = true;
        }
        this.emit("message", msg);
      } catch (e) {
        logger.error("[AgentProcess] JSON 解析失败:", trimmed);
      }
    }
  }
}
