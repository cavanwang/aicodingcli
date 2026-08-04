# Phase 9：对标 Claude Code — 功能追赶路线图

## 目标
以 Claude Code 为标杆，补齐当前项目与主流 coding agent 的功能差距，提升项目定制化能力、交互便捷性和工程成熟度。

> 原则：优先做投入小、收益大的功能；架构改动大的功能暂缓。

---

## 当前能力基线（Phase 1-8 已完成）

| 能力 | 状态 |
|---|---|
| 多文件编辑（edit_file / batch_edit） | ✅ |
| 工具调用链（读/写/搜索/执行） | ✅ |
| 安全沙箱（sandbox-exec + 黑名单 + 资源限制） | ✅ |
| Todo 任务追踪（持久化 + 进度注入） | ✅ |
| 跨会话代码记忆（CodeMemory） | ✅ |
| 错误自愈（RecoveryManager） | ✅ |
| Git 集成（checkpoint / rollback / diff） | ✅ |
| 执行轨迹（ExecutionTracer） | ✅ |
| Token 统计（UsageTracker） | ✅ |
| 历史压缩（compress_history） | ✅ |
| 流式输出（Rich console） | ✅ |
| 破坏性操作确认（CONFIRM_TOOLS） | ✅ |
| 变更审查（ChangeReviewer） | ✅ |
| 测试自动生成（generate_tests） | ✅ |
| 项目上下文感知（build_context） | ✅ |
| 危险命令拦截（CommandGuard） | ✅ |

---

## 方向一：项目级配置系统（对标 CLAUDE.md）

### Claude Code 做法
项目根目录放 `CLAUDE.md`，定义项目专属规则：编码规范、常用命令、技术栈偏好、禁止事项。Agent 启动时自动加载，注入 system prompt。

### 当前差距
system prompt 全局写死在 `config.py`，无法按项目定制。

### 实现内容

**1.1 项目配置文件加载**
- 新增 `agent/project_config.py`
- 自动查找项目根目录下的 `.agent.md`（或 `AGENT.md`）
- 解析 markdown 内容，提取规则、命令、规范
- 注入到 system prompt 尾部

**1.2 配置文件模板**
- 提供 `.agent.md` 模板，包含常用段落：
  - 项目简介
  - 技术栈
  - 编码规范
  - 常用命令
  - 禁止事项

**1.3 多层级配置**
- 全局配置：`~/.aicoding/config.md`（所有项目共享）
- 项目配置：`{project}/.agent.md`（项目专属）
- 项目配置覆盖全局配置

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `agent/project_config.py` | 项目配置加载器 |
| 修改 | `agent/core.py` | 启动时加载项目配置 |
| 修改 | `config.py` | system prompt 拼接逻辑调整 |
| 新增 | `tests/test_project_config.py` | 配置加载测试 |

---

## 方向二：Slash 命令系统（对标 /init /compact /review 等）

### Claude Code 做法
用户输入 `/` 开头的命令触发内置功能，不经过 LLM。常用命令：
- `/compact` — 手动压缩历史
- `/cost` — 查看本次会话花费
- `/clear` — 清空对话
- `/help` — 显示帮助
- `/init` — 初始化项目配置
- `/review` — 对当前变更做代码审查
- `/doctor` — 诊断环境健康状态
- `/status` — 显示当前状态
- `/quit` — 退出

### 当前差距
只有 `quit` / `exit` / `q`，无扩展机制。

### 实现内容

**2.1 命令注册与分发**
- 新增 `cli/commands.py`
- 定义命令注册表：`{name: (handler, description)}`
- `ui.py` 中用户输入以 `/` 开头时，分发到命令处理器

**2.2 内置命令**
- `/help` — 显示所有可用命令
- `/compact` — 手动触发历史压缩
- `/cost` — 显示本次会话 Token 用量和费用估算
- `/clear` — 清空对话历史
- `/status` — 显示当前状态（模型、目录、消息数、Token、计划进度、Todo 进度）
- `/review` — 手动触发变更审查（复用 ChangeReviewer）
- `/doctor` — 诊断环境健康状态（API 连通性、key 有效性、沙箱可用性）
- `/usage` — 显示历史用量（最近 7 天）
- `/todo` — 显示当前 Todo 列表
- `/plan` — 显示当前任务计划
- `/memory` — 显示代码记忆摘要
- `/init` — 在当前目录生成 `.agent.md` 模板

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `cli/commands.py` | Slash 命令注册与分发 |
| 修改 | `cli/ui.py` | 接入命令分发逻辑 |
| 新增 | `tests/test_commands.py` | 命令测试 |

---

## 方向三：费用估算（对标 /cost）

### Claude Code 做法
实时显示本次会话的美元花费，基于 token 数量和模型单价计算。

### 当前差距
只统计 token 数，没有换算成费用。

### 实现内容

**3.1 模型价格表**
- 在 `agent/usage.py` 中增加常见模型的价格配置
- 支持通过环境变量覆盖

**3.2 费用计算**
- `UsageTracker` 增加 `estimated_cost()` 方法
- 公式：`prompt_tokens * input_price + completion_tokens * output_price`

**3.3 展示**
- 退出时同时展示 token 数和费用估算
- `/cost` 命令实时查看

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 修改 | `agent/usage.py` | 增加价格表和费用计算 |
| 修改 | `cli/ui.py` | 退出时展示费用 |

---

## 方向四：验证护栏增强（Phase 8 遗留）

### 当前差距
- review_changes 只输出文本，无 JSON 结构化
- 无 `agent rollback` CLI 子命令
- complete_step 不自动触发审查

### 实现内容

**4.1 结构化审查报告**
- `ReviewResult` 增加 `to_json()` 方法
- `review_changes` 支持 `format="json"` 参数

**4.2 CLI 回滚命令**
- `main.py` 新增 `rollback` 子命令
- 列出最近 checkpoint，一键恢复

**4.3 自动审查触发**
- `complete_step` 完成代码修改类子任务时，自动调用 `review_changes`

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 修改 | `agent/review.py` | 增加 `to_json()` |
| 修改 | `agent/tools/memory_tools.py` | review_changes 支持 format |
| 修改 | `main.py` | 新增 rollback 子命令 |
| 修改 | `agent/tools/task_tools.py` | complete_step 触发审查 |

---

## 方向五：Token 统计完善（Phase 8 遗留）

### 当前差距
- 无 `agent usage` 子命令查看历史
- 无满意度反馈

### 实现内容

**5.1 `agent usage` 子命令**
- `main.py` 新增 `usage` 子命令
- 复用 `UsageTracker.load_history()` 展示最近 7 天用量

**5.2 满意度反馈（可选）**
- 会话结束时询问满意度（1-5 分，可跳过）
- 记录到 `~/.aicoding/feedback/`

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 修改 | `main.py` | 新增 usage 子命令 |

---

## 方向六：智能上下文管理（对标 context window 管理）

### Claude Code 做法
自动判断 context window 使用情况，智能选择注入哪些文件/代码，避免超出限制。

### 当前差距
有历史压缩，但没有智能的 context 预算分配。

### 实现内容

**6.1 Token 预算感知**
- 在每次 API 调用前，估算当前 messages 的 token 数
- 接近模型上限时，自动触发历史压缩

**6.2 工具结果智能截断**
- 大文件读取结果按相关性截断，而非固定字符数
- 命令输出按尾部保留（错误信息通常在末尾）

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `agent/context_budget.py` | Token 预算估算与自动压缩 |
| 修改 | `agent/core.py` | 接入预算感知 |

---

## 实施优先级

| 优先级 | 方向 | 预估工作量 | 理由 |
|---|---|---|---|
| **P0** | 方向二：Slash 命令系统 | 小（~200行） | 投入小收益大，提升交互体验 |
| **P0** | 方向一：项目级配置 | 小（~200行） | 每个项目可定制，实用性极高 |
| **P1** | 方向三：费用估算 | 极小（~50行） | 几行代码即可 |
| **P1** | 方向四：验证护栏增强 | 中（~300行） | Phase 8 遗留，结构化输出有价值 |
| **P1** | 方向五：Token 统计完善 | 极小（~30行） | Phase 8 遗留，一个子命令 |
| **P2** | 方向六：智能上下文管理 | 中（~200行） | 有价值但当前历史压缩已够用 |

---

## 里程碑

- **M1**：Slash 命令可用 — `/help` `/compact` `/cost` `/clear` `/status` `/review` `/doctor` `/todo` `/init`
- **M2**：项目配置系统 — `.agent.md` 自动加载，项目级定制
- **M3**：费用可追踪 — 退出时显示费用估算
- **M4**：验证护栏完成 — JSON 审查 + rollback CLI
- **M5**：上下文智能管理 — Token 预算感知 + 自动压缩
