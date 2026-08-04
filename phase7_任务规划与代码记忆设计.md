# Phase 7 功能补全设计方案

## 功能一：任务规划与分阶段执行

### 目标
让 Agent 面对复杂任务时，能自动拆解为有序子任务，逐步执行并跟踪进度，而不是在一个大任务中迷失方向。

### 核心设计

**数据模型** — 新增 `agent/task_planner.py`

```python
class SubTask:
    id: int                    # 序号，从 1 开始
    description: str           # 子任务描述
    status: str                # "pending" | "in_progress" | "done" | "failed" | "skipped"
    result: str                # 执行结果摘要

class TaskPlan:
    task_id: str               # 时间戳生成，如 "plan_20250804_143022"
    goal: str                  # 用户原始目标
    subtasks: list[SubTask]    # 有序子任务列表
    created_at: datetime
    status: str                # "planning" | "executing" | "completed" | "failed"
```

**核心类 TaskPlanner**：
- `create_plan(goal, subtasks_desc) -> TaskPlan` — 从 LLM 输出或用户输入创建计划
- `get_next() -> SubTask | None` — 获取下一个待执行子任务
- `mark_done(task_id, result)` / `mark_failed(task_id, reason)` — 更新状态
- `progress_summary() -> str` — 返回进度文本，如 "3/5 完成，当前：xxx"
- `save() / load()` — 计划持久化到 `~/.aicoding/plans/`

**与 Agent 的集成** — 修改 `agent/core.py`

在 Agent 的 `chat()` 方法中增加任务规划感知：

1. 新增工具 `create_plan`：LLM 分析用户复杂请求后，调用此工具生成执行计划
2. 新增工具 `next_step`：获取并标记下一个子任务为 in_progress
3. 新增工具 `complete_step`：标记当前子任务完成，附带结果摘要
4. 新增工具 `plan_status`：查看整体进度

工具注册到 `agent/tools/task_tools.py`，在 `registry.py` 中注册。

**System Prompt 增强** — 修改 `config.py`

在 SYSTEM_PROMPT 中追加任务规划指引：
```
## 任务规划
- 收到复杂任务时（涉及 3 个以上步骤），先调用 create_plan 拆解任务
- 每完成一步，调用 complete_step 记录结果
- 开始下一步前，调用 next_step 获取任务
- 简单任务不需要规划，直接执行即可
```

**CLI 进度展示** — 修改 `cli/ui.py`

在 Agent 输出时展示当前计划进度条，如：
```
[Plan 1/3] 重构用户模块 ████████░░ 2/3
```

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `agent/task_planner.py` | TaskPlan / SubTask 数据模型 + 持久化 |
| 新增 | `agent/tools/task_tools.py` | create_plan / next_step / complete_step / plan_status 工具函数 |
| 修改 | `agent/tools/registry.py` | 注册 4 个新工具 |
| 修改 | `agent/core.py` | Agent 持有 TaskPlanner 实例，chat() 中注入计划进度上下文 |
| 修改 | `config.py` | SYSTEM_PROMPT 追加任务规划指引 |
| 修改 | `cli/ui.py` | 展示计划进度 |
| 新增 | `tests/test_task_planner.py` | TaskPlanner 单元测试 |
| 新增 | `tests/test_task_tools.py` | 工具函数单元测试 |

---

## 功能二：Agent Memory + Review

### 2A. 跨会话 Memory

**目标**：让 Agent 在多次会话间保持对代码库的"心理模型"，不用每次从零扫描。

**数据模型** — 新增 `agent/memory.py`

```python
class CodeMemory:
    file_summaries: dict[str, str]       # 文件路径 -> 职责摘要
    key_interfaces: dict[str, list[str]]  # 文件路径 -> [关键类/函数名]
    project_facts: list[str]              # 项目级事实，如 "使用 pytest 做测试"
    last_updated: datetime
```

**核心类 CodeMemory**：
- `load() -> CodeMemory` — 从 `~/.aicoding/memory/project_memory.json` 加载
- `save()` — 持久化到磁盘
- `update_from_scan(scan_result)` — 从 project.py 的扫描结果初始化/更新
- `update_file_summary(file_path, summary)` — 更新单个文件的摘要
- `get_context() -> str` — 生成记忆上下文字符串，注入 system prompt
- `should_refresh(file_paths) -> bool` — 判断某些文件是否有变更需要重新摘要

**与现有模块的集成**：
- `agent/core.py`：Agent 初始化时加载 CodeMemory，注入到 system prompt
- `agent/tools/task_tools.py`：新增 `update_memory(key, value)` 工具，让 LLM 主动更新记忆
- `agent/project.py`：`build_context()` 执行后，将扫描结果同步到 CodeMemory
- 会话结束时（quit），自动 save memory

**存储格式**：
```
~/.aicoding/memory/project_memory.json
```

### 2B. 修改后自动 Review

**目标**：一批修改完成后，自动审查变更质量，给出结构化报告。

**核心设计** — 新增 `agent/review.py`

```python
class ReviewResult:
    files_changed: list[str]
    lines_added: int
    lines_removed: int
    tests_found: list[str]
    tests_passed: int
    tests_failed: int
    risk_level: str           # "low" | "medium" | "high"
    suggestions: list[str]    # 改进建议
```

**核心类 ChangeReviewer**：
- `review() -> ReviewResult` — 执行一次完整审查：
  1. 调用 `analyze_changes()` 获取变更统计
  2. 调用 `verify_changes()` 运行相关测试
  3. 基于变更范围和测试结果评估风险等级
  4. 生成改进建议
- `format_report(result) -> str` — 格式化为可读报告

**触发时机**：
- 新增工具 `review_changes`：LLM 或用户主动触发
- 可选：在 `complete_step` 时自动触发（当子任务涉及代码修改时）

### 涉及文件
| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `agent/memory.py` | CodeMemory 数据模型 + 持久化 + 上下文生成 |
| 新增 | `agent/review.py` | ChangeReviewer 审查逻辑 |
| 新增 | `agent/tools/memory_tools.py` | update_memory / review_changes 工具函数 |
| 修改 | `agent/tools/registry.py` | 注册 update_memory / review_changes |
| 修改 | `agent/core.py` | Agent 持有 CodeMemory，初始化时加载，注入上下文 |
| 修改 | `config.py` | SYSTEM_PROMPT 追加 memory 和 review 使用指引 |
| 修改 | `cli/ui.py` | 展示 review 报告 |
| 新增 | `tests/test_memory.py` | CodeMemory 单元测试 |
| 新增 | `tests/test_review.py` | ChangeReviewer 单元测试 |

---

## 实施顺序

建议按以下顺序推进，每步都可独立验证：

1. **task_planner.py** — 数据模型 + 持久化（纯逻辑，先做稳）
2. **task_tools.py + registry 注册** — 工具暴露给 LLM
3. **core.py 集成** — Agent 接入 TaskPlanner
4. **test_task_planner.py** — 验证计划引擎
5. **memory.py** — 数据模型 + 持久化
6. **memory_tools.py + registry 注册** — 工具暴露
7. **core.py 集成 Memory** — Agent 接入 CodeMemory
8. **test_memory.py** — 验证记忆模块
9. **review.py** — 审查逻辑（依赖已有的 analyze_changes + verify_changes）
10. **review 工具注册 + 集成** — 工具暴露 + CLI 展示
11. **test_review.py** — 验证审查模块
12. **config.py + ui.py 最终调整** — prompt 增强 + 进度/报告展示

## 新增工具汇总

| 工具名 | 用途 | 需确认 |
|---|---|---|
| `create_plan` | 创建任务执行计划 | 否 |
| `next_step` | 获取下一个子任务 | 否 |
| `complete_step` | 标记子任务完成 | 否 |
| `plan_status` | 查看计划进度 | 否 |
| `update_memory` | 更新代码库记忆 | 否 |
| `review_changes` | 审查当前变更质量 | 否 |
