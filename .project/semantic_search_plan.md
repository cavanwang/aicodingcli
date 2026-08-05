# 语义搜索基础版实施规划

## 一、总体规划大纲

### 🎯 核心目标
实现行业标准的语义代码搜索能力，使 `aicoding search --semantic` 命令能准确识别语义相似代码片段（如用自然语言查询"找出所有分页处理逻辑"）。

### ⏱️ 时间线
| 阶段         | 预计耗时 | 交付物                     |
|--------------|----------|----------------------------|
| 模型集成     | 3人日    | 可运行的代码嵌入引擎       |
| 增量索引     | 4人日    | git感知的向量索引系统      |
| 工具扩展     | 2人日    | 语义搜索CLI接口            |
| 验证体系     | 3人日    | 10+验证用例+CI集成        |
| 文档沉淀     | 1人日    | 自动更新的项目记忆文档     |
| **总计**     | **13人日** | **完整交付P0能力**        |

### 📐 质量红线
1. **性能底线**：1000行文件索引时间 ≤ 500ms
2. **精度底线**：10个典型查询准确率 ≥ 75%
3. **安全底线**：误匹配率 ≤ 15%（双重验证机制保障）

---

## 二、子任务详细规划

### 1️⃣ 【模型集成】CodeBERTa嵌入引擎实现
#### 📌 核心目标
构建轻量级代码向量化能力，支持512 token截断的Python代码嵌入生成

#### ✅ 验收标准
| 指标                | 达标值                 | 验证方式                     |
|---------------------|------------------------|------------------------------|
| 向量生成延迟        | ≤ 300ms/文件           | `pytest test_semantic.py`    |
| 相似度计算误差      | ≤ 5% (vs ground truth) | 人工对比验证                 |
| 内存占用            | ≤ 200MB                | `memory_profiler` 监控       |

#### 🛠️ 实施步骤
| 步骤 | 任务描述                          | 产出物                          | 风险应对                     |
|------|-----------------------------------|---------------------------------|------------------------------|
| 1    | 添加依赖到`pyproject.toml`        | ```toml
[tool.poetry.dependencies]
transformers = "^4.35"
torch = "^2.1"
``` | 使用`poetry add`避免版本冲突 |
| 2    | 实现`agent/semantic.py`核心引擎   | ```python
class CodeEmbedder:
    def __init__(self):
        self.tokenizer = AutoTokenizer.from_pretrained("huggingface/CodeBERTa-small-v1")
        self.model = AutoModel.from_pretrained("huggingface/CodeBERTa-small-v1")

    def embed(self, code: str) -> np.ndarray:
        inputs = self.tokenizer(code, return_tensors="pt", truncation=True, max_length=512)
        outputs = self.model(**inputs)
        return outputs.last_hidden_state.mean(dim=1).detach().numpy()
``` | 首次加载超时 → 后台预加载线程 |
| 3    | 编写单元测试                      | `tests/test_semantic.py`<br>- 验证向量稳定性<br>- 测试截断边界情况 | 模型下载失败 → 本地缓存镜像 |

#### 🧪 关键验证用例
```python
# 测试向量一致性
def test_embedding_stability():
    embedder = CodeEmbedder()
    code1 = "def paginate(items, page_size): return items[page*page_size:(page+1)*page_size]"
    code2 = "def get_page(data, size): return data[page*size:(page+1)*size]"
    vec1 = embedder.embed(code1)
    vec2 = embedder.embed(code2)
    assert cosine_similarity(vec1, vec2) > 0.85  # 语义相似应高相似度
```

---

### 2️⃣ 【增量索引】Git感知的FAISS索引系统
#### 📌 核心目标
实现变更驱动的索引更新机制，仅处理`git diff`涉及的文件

#### ✅ 验收标准
| 指标                | 达标值                 | 验证方式                     |
|---------------------|------------------------|------------------------------|
| 索引构建速度        | ≤ 500ms/1000行文件     | `time aicoding index`        |
| 索引准确性          | 100%覆盖变更文件       | 人工检查索引日志             |
| 存储开销            | ≤ 50MB/万行代码        | `du -sh .cache/semantic.index` |

#### 🛠️ 实施步骤
| 步骤 | 任务描述                          | 产出物                          | 风险应对                     |
|------|-----------------------------------|---------------------------------|------------------------------|
| 1    | 扩展`project.py`索引接口          | ```python
def update_semantic_index():
    changed_files = run_command("git diff --name-only HEAD").splitlines()
    for file in changed_files:
        if file.endswith(".py"):
            code = read_file(file)
            vector = embedder.embed(code)
            faiss_index.add(vector, file)
``` | 处理大仓库 → 分页处理diff    |
| 2    | 实现FAISS索引持久化               | `.cache/semantic.index`<br>包含：<br>- 向量数据库<br>- 文件路径映射<br>- 版本标识 | 索引损坏 → 自动重建机制      |
| 3    | 集成git钩子自动触发               | `.git/hooks/post-commit`<br>```bash
#!/bin/sh
aicoding update-index
``` | 钩子冲突 → 用户可选启用      |

#### 🧪 关键验证用例
```bash
# 模拟变更场景
echo "def new_pagination(): pass" >> src/utils.py
git add . && git commit -m "test"

# 验证索引更新
aicoding search --semantic "分页逻辑"
# 应返回包含src/utils.py的结果
```

---

### 3️⃣ 【工具扩展】语义搜索接口增强
#### 📌 核心目标
无缝扩展现有搜索工具，保持向后兼容的同时新增语义模式

#### ✅ 验收标准
| 指标                | 达标值                 | 验证方式                     |
|---------------------|------------------------|------------------------------|
| 接口兼容性          | 旧命令100%可用         | `aicoding search "old_query"` |
| 语义查询响应        | ≤ 1s (100文件内)       | `time aicoding search --semantic ...` |
| 误匹配率            | ≤ 15%                  | 人工审核前10结果             |

#### 🛠️ 实施步骤
| 步骤 | 任务描述                          | 产出物                          | 风险应对                     |
|------|-----------------------------------|---------------------------------|------------------------------|
| 1    | 扩展`search.py`核心逻辑           | ```python
def semantic_search(query: str, threshold: float = 0.85):
    query_vec = embedder.embed(query)
    results = faiss_index.search(query_vec, k=10)
    return [r for r in results if r.score >= threshold]
``` | 模型未加载 → 自动降级关键词搜索 |
| 2    | 实现AST结构验证                   | ```python
def validate_semantic_match(code: str, query: str) -> bool:
    # 验证关键结构匹配（如分页必含切片操作）
    return "[:]" in code or "slice" in code
``` | 过滤过严 → 动态调整规则库    |
| 3    | CLI参数扩展                       | ```python
parser.add_argument("--semantic", action="store_true", help="启用语义搜索模式")
parser.add_argument("--threshold", type=float, default=0.85, help="相似度阈值")
``` | 参数冲突 → 优先级明确说明    |

#### 🧪 关键验证用例
```bash
# 测试语义搜索
aicoding search --semantic "用户登录失败处理"
# 预期返回：
# auth.py:45 - 处理密码错误
# sso.py:112 - 处理第三方认证失败
```

---

### 4️⃣ 【CLI验证】端到端验证体系
#### 📌 核心目标
构建可量化的验证框架，确保搜索质量达标

#### ✅ 验收标准
| 指标                | 达标值                 | 验证方式                     |
|---------------------|------------------------|------------------------------|
| 测试覆盖率          | ≥ 80% 核心路径         | `pytest --cov`               |
| 评估一致性          | 3人交叉验证Kappa ≥ 0.7 | 人工评估表                   |
| CI集成              | 每次PR自动运行         | GitHub Actions流水线         |

#### 🛠️ 实施步骤
| 步骤 | 任务描述                          | 产出物                          | 风险应对                     |
|------|-----------------------------------|---------------------------------|------------------------------|
| 1    | 创建语义测试用例库                | `tests/semantic_cases/`<br>包含：<br>- 10+典型查询<br>- 预期结果集<br>- 人工评估记录 | 用例偏差 → 定期更新用例库    |
| 2    | 开发验证脚本                      | `tools/verify_semantic.py`<br>```python
def evaluate(query, expected_files):
    results = semantic_search(query)
    return precision_at_k(results, expected_files)
``` | 评估主观 → 量化评分标准      |
| 3    | CI流水线集成                      | `.github/workflows/semantic-test.yml`<br>```yaml
- name: Run semantic validation
  run: python tools/verify_semantic.py --min-accuracy 0.75
``` | CI超时 → 并行化测试          |

#### 📊 评估表示例
| 查询示例                | 预期文件              | 实际命中 | 准确率 | 评估人 |
|-------------------------|-----------------------|----------|--------|--------|
| "分页处理逻辑"         | [utils.py, api.py]    | 2/2      | 100%   | Alice  |
| "用户登录失败处理"     | [auth.py, sso.py]     | 1/2      | 50%    | Bob    |

---

### 5️⃣ 【文档沉淀】自动化记忆系统
#### 📌 核心目标
实现知识自动沉淀，确保能力可传承

#### ✅ 验收标准
| 指标                | 达标值                 | 验证方式                     |
|---------------------|------------------------|------------------------------|
| 文档及时性          | 代码提交后自动更新     | 检查`.agent/memory.md`时间戳 |
| 模式记录完整性      | 包含所有验证通过的模式 | 人工审核文档                 |
| 用户可理解性        | 新成员10分钟掌握用法   | 新人上手测试                 |

#### 🛠️ 实施步骤
| 步骤 | 任务描述                          | 产出物                          | 风险应对                     |
|------|-----------------------------------|---------------------------------|------------------------------|
| 1    | 扩展`save_memory`自动捕获         | ```python
def save_pattern(pattern: str, examples: list[str]):
    content = f"- `{pattern}`: {examples[0]}等{len(examples)}处"
    save_memory("append", "## 代码模式", content)
``` | 误捕获 → 人工确认流程        |
| 2    | 生成实施进度追踪                  | 自动更新`.project/roadmap.md`<br>```markdown
### 语义搜索基础版
- [x] 模型集成 (2024-08-05)
- [ ] 增量索引
``` | 进度滞后 → 提交前检查        |
| 3    | 更新用户文档                      | `README.md`新增语义搜索章节<br>```markdown
## 语义搜索
```bash
aicoding search --semantic "处理异常"
``` | 文档过时 → CI文档检查        |

#### 📚 自动生成文档示例
```markdown
## 代码模式
- `分页处理`: utils.py#L45, api.py#L102等3处
- `错误重试机制`: network.py#L88, db.py#L201等2处
```

---

## 三、风险控制矩阵

| 风险点                | 概率 | 影响 | 应对措施                                  | 负责人   |
|-----------------------|------|------|-------------------------------------------|----------|
| 模型加载超时          | 高   | 高   | 1. 后台预加载线程<br>2. 首次使用异步下载 | 工具链组 |
| 索引膨胀              | 中   | 中   | 1. 限制.py文件<br>2. 512 token截断      | 数据组   |
| 语义误匹配            | 高   | 高   | 1. 0.85阈值<br>2. AST结构验证           | 质量组   |
| 评估偏差              | 中   | 中   | 3人交叉验证+Kappa系数监控               | 测试组   |
| 文档滞后              | 高   | 低   | CI强制文档检查+提交前拦截               | 文档组   |

> **熔断机制**：当任一验证指标连续3次不达标，自动触发`git_rollback`并重新规划