/**
 * Agent 子进程管理：spawn Python --server 进程，通过 JSON Lines 通信。
 */

import { ChildProcess, spawn } from "child_process";
import { EventEmitter } from "events";

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
      console.error("[Agent stderr]", data.toString().trim());
    });

    this._child.on("error", (err: Error) => {
      this.emit("error", err);
    });

    this._child.on("close", (code: number | null) => {
      this._ready = false;
      this.emit("close", code);
    });
  }

  /**
   * 停止子进程。
   */
  stop(): void {
    if (this._child) {
      this.send({ type: "quit" });
      setTimeout(() => {
        if (this._child && !this._child.killed) {
          this._child.kill("SIGTERM");
        }
      }, 2000);
      this._child = null;
      this._ready = false;
    }
  }

  /**
   * 发送聊天消息。
   */
  chat(message: string): void {
    this.send({ type: "chat", message });
  }

  /**
   * 发送心跳。
   */
  ping(): void {
    this.send({ type: "ping" });
  }

  /**
   * 发送 JSON 消息到子进程 stdin。
   */
  private send(msg: object): void {
    if (!this._child?.stdin?.writable) {
      console.warn("[Agent] 进程未运行，无法发送消息");
      return;
    }
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
        if (msg.type === "ready") {
          this._ready = true;
        }
        this.emit("message", msg);
      } catch (e) {
        console.error("[Agent] JSON 解析失败:", trimmed, e);
      }
    }
  }
}
