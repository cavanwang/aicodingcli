# 智能代码理解能力规划（Phase 11）

> 本文档取代旧版《语义搜索基础版实施规划》（CodeBERTa 本地方案，已评审淘汰）。
> 技术路线修正说明见文末附录。

## 一、对标分析：Claude Code / Codex 的理解能力本质

| 能力 | Claude Code / Codex 做法 | 本项目现状 |
|------|------------------------|-----------|
| 代码检索 | **agentic search 策略**（glob → grep → read 多轮迭代）+ 大仓库用 embeddings | 有 grep/find_files 单发工具，无搜索策略引导 |
| 符号导航 | AST/LSP 级定义跳转、引用查找 | `ast_analyzer.py` 已实现但未暴露给模型 |
| 依赖追踪 | import 链 / call graph 分析 | `get_related_files` 部分能力 |
| 项目记忆 | CLAUDE.md / AGENTS.md 持久化 | `project_memory` 已实现 ✅ |
| 大仓库语义检索 | 后台 embedding 索引 | 无 |
| 上下文管理 | 按需加载 + 会话压缩 | ContextManager 有基础 |

**核心洞察**：Claude Code 证明了——**检索策略 + 精确符号工具的价值远大于盲目上向量索引**。
向量检索只在大仓库（>500 文件）才是刚需。

## 二、现有能力盘点

| 模块 | 能力 | 状态 |
|------|------|------|
| `agent/tools/search.py` | grep 式关键词搜索 | ✅ 已注册为工具 |
| `agent/tools/find_files.py` | glob 文件名查找 | ✅ 已注册为工具 |
| `agent/ast_analyzer.py` | AST 定义跳转 / 引用查找 | ⚠️ 已实现，**未注册为工具** |
| `agent/project.py` | 项目扫描、模块概览、import 提取 | ✅ 部分注入 system prompt |
| `agent/project_memory.py` | CLAUDE.md 式持久化记忆 | ✅ 已实现 |
| `agent/context.py` | 上下文管理 | ✅ 基础能力 |
| `get_related_files` 工具 | 相关文件推荐 | ✅ 已注册 |

## 三、五大任务

### 任务 A：探索策略内化（Search Strategy）
**目标**：把 Claude Code 的 agentic search 方法论注入 system prompt + 工具描述，
让模型以"由宽到窄、多工具迭代收敛"的方式探索代码，禁止凭猜测修改。

**子任务**：
- A1. system prompt 强化（config.py）：合并强化现有探索章节，新增
  - 迭代收敛搜索法：find_files 定位候选 → search_in_files 精确定位 → read_file 读上下文；
    结果太多收窄模式，没结果换同义词/换工具
  - 修改前探索准则：改函数前先搜索调用方理解影响面；未读实际代码禁止修改
  - 理解验证闭环：对不确定的行为假设用 run_command 做最小验证
- A2. 工具描述增强（registry.py）：为 find_files / search_in_files / read_file /
  list_directory 补充使用场景与组合提示
- A3. ~~explore_codebase 元工具~~ → **本轮不做**（与 A1+A2 及任务 B 能力重叠，
  待 B 完成后重新评估）

**验收标准**：用本仓库端到端提问（如"找出所有处理会话压缩的逻辑"），
观察 Agent 按新策略迭代搜索而非直接猜测。

**成本**：0.5~1 人日 | **依赖**：无 | **风险**：极低

---

### 任务 B：符号导航工具化（Symbol Navigation）
**目标**：将已有的 `ast_analyzer.py` 注册为 Agent 工具，补齐精确符号级导航。

**子任务**：
- B1. 注册 `find_definition(symbol, file?)` 工具（跨文件符号定位）
- B2. 注册 `find_references(symbol)` 工具（全 workspace 引用查找）
- B3. 新增 `get_import_tree(file)`：import 链正反向追踪
  （复用 project.py 已有的 import 提取逻辑）

**验收标准**：
- 对 `Agent` 类调用 find_references 能返回 core.py/main.py 等全部引用位置
- get_import_tree("agent/core.py") 能输出正反向 import 链

**成本**：1~2 人日 | **依赖**：无 | **风险**：低（存量代码封装）

---

### 任务 C：语义搜索 API 版（Semantic Search）
**目标**：为大仓库场景提供自然语言 → 代码的语义检索兜底能力。

**子任务**：
- C1. AST 分块器：按函数/类切分代码 chunk（复用 AST 能力），避免整文件截断
- C2. Embedding 引擎：DashScope `text-embedding-v3` API（与现有 qwen 同密钥体系），
  重写 `agent/semantic.py`（现版本基于 CodeBERTa，路线已淘汰）
- C3. 内容哈希增量索引：`.cache/semantic/` 存储 chunk 向量 + 文件哈希，
  仅重新嵌入变更文件
- C4. `semantic_search` 工具注册：numpy 余弦相似度检索 top-k，
  失败时降级到关键词搜索
- C5. 10 个查询用例的 pytest 回归验证（含中英文跨模态查询）

**验收标准**：
- "分页处理逻辑" 能命中实际的分页实现函数
- 增量索引：单文件变更后仅重嵌该文件
- API 不可用时自动降级不报错

**成本**：3~5 人日 | **依赖**：任务 B（分块复用 AST）；需 DashScope embedding API 权限
**风险**：中 | **附加清理**：移除 torch/transformers 依赖

---

### 任务 D：上下文智能管理（Context Intelligence）
**目标**：让有限的上下文窗口装载最高价值的信息。

**子任务**：
- D1. 相关性排序：`get_related_files` 融合 git 共现历史
  （git log 中经常一起提交的文件权重更高）
- D2. 会话压缩：长对话自动摘要历史轮次（保留最近 N 轮 + 摘要）
- D3. 记忆按需注入：按当前任务关键词筛选 project_memory 相关段落，而非全量注入

**验收标准**：
- 修改 core.py 时，related_files 能把高频共现的 main.py 排在前列
- 30 轮以上对话不超出上下文窗口且关键信息不丢失

**成本**：2~4 人日 | **依赖**：D2 可独立，D1 建议在 C 之后 | **风险**：中（涉及 Agent 主流程）

---

### 任务 E：执行验证驱动理解（Verification-Driven Understanding）
**目标**：模型对不确定的代码行为"先验证再结论"，并自动沉淀探索成果。

**子任务**：
- E1. "假设-验证"模式引导：prompt 要求模型对不确定行为先写最小验证脚本 /
  run_command 确认，再下结论
- E2. 项目画像自动更新：探索/修改中发现的关键事实自动 append 到 project_memory

**验收标准**：
- 提问含隐含行为假设的问题时，Agent 主动运行验证而非直接推断
- 探索新项目后 .agent/memory.md 自动新增有效条目

**成本**：1~2 人日 | **依赖**：任务 A | **风险**：低

## 四、依赖关系与实施顺序

```
任务A（探索策略）──┬──> 任务E（验证驱动）
                  └──> 任务D2（会话压缩）
任务B（符号导航）────> 任务C（语义搜索）────> 任务D1（相关性排序）
```

**推荐顺序：A → B → C → D → E**

理由：
1. A 工作量最小且是所有能力的"放大器"，立刻提升探索质量
2. B 是存量代码变现，性价比最高
3. 有了 A+B，语义搜索（C）只需解决"大仓库兜底"，验收标准可放宽
4. D/E 建立在前面能力之上做优化

**总成本估算**：7.5~14 人日（对比旧方案单语义搜索即 13 人日）

## 五、验证体系

- 每任务完成后用本仓库做端到端回归（自举测试）
- 任务 C 附 pytest 用例库（tests/ 下，遵循现有 WORKSPACE_DIR 路径基准约定）
- 不引入 CI / 多人交叉验证流程（个人项目，以自动化回归脚本为准）

## 附录：技术路线修正说明（为什么淘汰旧方案）

旧方案（CodeBERTa 本地嵌入 + FAISS）的致命缺陷：
1. **模型选型错误**：CodeBERTa-small-v1 是 MLM 预训练模型，未做相似度微调，
   mean-pooling 向量检索质量差；且为纯代码模型，中文自然语言查询跨模态检索基本无效
2. **分块粒度错误**：整文件一个向量 + 512 token 截断，大文件后半部分永远检索不到
3. **架构冲突**：项目是纯 API 架构（openai SDK + qwen），引入 torch+transformers
   （约 2GB）拖慢 CLI 启动
4. **增量机制有错**：`git diff --name-only HEAD` 只覆盖未提交改动；
   FAISS 伪代码（add(vector, file)）不是真实 API
5. **流程不匹配**：3 人 Kappa 验证、CI 流水线、团队分工等模板对个人项目不可执行

修正后路线：DashScope embedding API + AST 函数级分块 + numpy 余弦检索 + 内容哈希增量。

**遗留清理项**（任务 C 实施时处理）：
- 重写 `agent/semantic.py`（现为 CodeBERTa 实现，未被引用）
- 从 requirements.txt 移除 `transformers`、`torch`
