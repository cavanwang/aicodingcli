# Phase 8：核心能力强化路线图

## 目标
在 Phase 1-7 基础上，补齐主流 coding agent 的标配能力，提升安全性、上下文理解精度、验证可靠性和任务编排能力。

---

## 方向一：安全加固 — 命令防护与资源限制

### 目标
防止 Agent 执行危险命令或耗尽系统资源，建立工程底线。

### 当前现状
- ✅ 命令白名单（`shell.py` 中有限制）
- ✅ 修改型操作确认机制
- ✅ checkpoint/rollback 保护
- ❌ 无危险命令黑名单
- ❌ 无超时熔断
- ❌ 无资源限制（CPU/内存）

### 实现内容

**1.1 危险命令黑名单**
- 新增 `agent/security.py` 模块
- 定义高危命令模式：`rm -rf /`、`sudo`、`chmod 777`、`dd if=`、`mkfs` 等
- 在 `run_command` 执行前拦截，返回警告而非执行
- 支持用户配置自定义黑名单

**1.2 超时与资源限制**
- `run_command` 增加 `timeout` 参数（默认 60s）
- 超时自动终止子进程
- 可选：通过 `resource.setrlimit()` 限制内存使用

**1.3 路径安全增强**
- 强化 `_safe_path`：禁止操作 `/etc`、`/usr`、`~/.ssh` 等系统敏感路径
- 文件写入前校验目标路径是否在 WORKSPACE_DIR 内

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `agent/security.py` | 安全策略模块（黑名单 + 路径校验） |
| 修改 | `agent/tools/shell.py` | 接入安全检查 + 超时机制 |
| 修改 | `config.py` | 新增安全相关配置项 |
| 新增 | `tests/test_security.py` | 安全模块测试 |

---

## 方向二：AST 级代码理解 — 函数调用图

### 目标
让 Agent 理解代码的函数级结构，而非仅停留在文件摘要层面。

### 当前现状
- ✅ `CodeMemory.key_interfaces` 记录关键类/函数名
- ✅ `generate_tests.py` 已使用 AST 分析
- ❌ 无函数调用关系图
- ❌ 无跨文件依赖分析

### 实现内容

**2.1 AST 解析器**
- 新增 `agent/code_analysis.py`
- 对 Python 文件提取：
  - 函数/类定义（名称、参数、返回类型注解）
  - 函数间调用关系（A 调用 B）
  - import 依赖关系
- 输出结构化的调用图数据

**2.2 集成到 CodeMemory**
- `update_memory` 支持 `action="analyze"` 对单文件做 AST 分析
- 分析结果存入 `key_interfaces`，格式升级为包含调用关系
- `get_context()` 输出中展示函数依赖

**2.3 智能上下文注入**
- 当 Agent 修改某函数时，自动查找调用方和被调用方
- 将相关文件路径注入上下文，提示 Agent 注意影响范围

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `agent/code_analysis.py` | AST 解析 + 调用图构建 |
| 修改 | `agent/memory.py` | 集成 AST 分析结果 |
| 修改 | `agent/tools/memory_tools.py` | 新增 analyze action |
| 新增 | `tests/test_code_analysis.py` | AST 分析测试 |

---

## 方向三：验证护栏增强 — 结构化输出与回滚

### 目标
让审查结果可被外部系统消费，并提供便捷的回滚操作。

### 当前现状
- ✅ `review_changes` 输出文本报告
- ✅ `verify_changes` 运行测试
- ✅ checkpoint 机制（git stash）
- ❌ 无结构化 JSON 输出
- ❌ 无 CLI 快捷回滚命令

### 实现内容

**3.1 结构化审查报告**
- `ChangeReviewer.review()` 返回的 `ReviewResult` 增加 `to_json()` 方法
- `review_changes` 工具支持 `format="json"` 参数，输出 JSON 格式
- JSON schema 定义：`files_changed`、`risk_level`、`tests_passed`、`suggestions`

**3.2 CLI 回滚命令**
- 新增 `agent rollback` 子命令
- 列出最近的 checkpoint，选择后一键恢复
- 复用现有 `git stash` / `git checkout` 逻辑

**3.3 自动审查触发**
- `complete_step` 完成涉及代码修改的子任务时，自动触发 `review_changes`
- 高风险变更（risk_level=high）自动暂停，等待用户确认

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 修改 | `agent/review.py` | 增加 `to_json()` + 风险阈值 |
| 修改 | `agent/tools/memory_tools.py` | review_changes 支持 format 参数 |
| 修改 | `main.py` 或 `cli/ui.py` | 新增 rollback 子命令 |
| 修改 | `agent/tools/task_tools.py` | complete_step 触发自动审查 |
| 新增 | `tests/test_review_json.py` | JSON 输出测试 |

---

## 方向四：任务编排增强 — 失败降级与工具链

### 目标
让 TaskPlanner 支持更智能的失败处理和多工具协调。

### 当前现状
- ✅ TaskPlanner 支持 create/next/complete/skip
- ✅ mark_failed 标记失败
- ❌ 失败后无自动重试/降级策略
- ❌ 无工具链模板（一个子任务绑定多个工具执行序列）

### 实现内容

**4.1 失败降级策略**
- SubTask 增加 `retry_count` 和 `max_retries` 字段
- 子任务失败时自动重试（默认最多 2 次）
- 超过重试上限后：跳过 or 标记计划失败（可配置）
- 失败时自动创建 checkpoint，便于回滚

**4.2 工具链模板**
- SubTask 增加可选 `tool_chain: list[str]` 字段
- 定义常用模板：
  - `edit_verify`: edit_file → verify_changes
  - `edit_test_review`: edit_file → run_command(test) → review_changes
- LLM 创建计划时可指定模板

**4.3 进度上下文注入**
- 每轮对话开始时，如果存在活跃计划，自动注入进度摘要到 system prompt
- 让 LLM 始终知道"当前做到哪了"

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 修改 | `agent/task_planner.py` | SubTask 增加重试 + 工具链字段 |
| 修改 | `agent/tools/task_tools.py` | 支持降级策略 |
| 修改 | `agent/core.py` | 自动注入计划进度到上下文 |
| 修改 | `tests/test_task_planner.py` | 新增降级策略测试 |

---

## 方向五：Token 用量统计与监控

### 目标
让用户了解每次会话的资源消耗，为后续优化提供数据基础。

### 当前现状
- ✅ `tracer.py` 记录工具调用链
- ✅ `logger.py` 记录运行日志
- ❌ 无 Token 消耗统计
- ❌ 无会话成本汇总

### 实现内容

**5.1 Token 统计**
- 在 `core.py` 的 LLM API 调用处，记录每次请求的 `usage` 字段
- 累计：`prompt_tokens`、`completion_tokens`、`total_tokens`
- 按会话汇总

**5.2 会话成本报告**
- 会话结束时（quit），输出本次会话的 Token 消耗汇总
- 持久化到 `~/.aicoding/usage/` 目录
- 支持 `agent usage` 命令查看历史用量

**5.3 简易反馈机制**
- 会话结束时询问满意度（1-5 分，可选跳过）
- 记录到 `~/.aicoding/feedback/` 目录

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 修改 | `agent/core.py` | 记录 token usage |
| 新增 | `agent/usage.py` | 用量统计与持久化 |
| 修改 | `cli/ui.py` | 退出时展示用量 + 反馈收集 |
| 修改 | `main.py` | 新增 `usage` 子命令 |
| 新增 | `tests/test_usage.py` | 用量统计测试 |

---

## 实施优先级建议

| 优先级 | 方向 | 理由 |
|---|---|---|
| P0 | 方向一：安全加固 | 工程底线，成本低风险高 |
| P1 | 方向三：验证护栏增强 | 在已有基础上增量，投入产出比高 |
| P1 | 方向五：Token统计 | 快速可落地，几行代码即可 |
| P2 | 方向四：任务编排增强 | 提升复杂任务成功率 |
| P2 | 方向二：AST代码理解 | 提升上下文精度，但工作量较大 |

---

## 里程碑

- **M1**：安全加固完成 — Agent 不会执行危险命令
- **M2**：验证护栏完成 — 审查结果可 JSON 输出 + 一键回滚
- **M3**：Token 统计完成 — 每次会话有成本报告
- **M4**：任务编排增强 — 失败自动重试/降级
- **M5**：AST 理解完成 — 函数级调用图可用
