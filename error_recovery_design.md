# 错误自愈能力设计方案

## 1. 目标

让这个 AI Coding CLI Agent 在遇到命令执行失败、测试失败、语法错误、依赖缺失等问题时，能够进入一个“分析 → 修复 → 重试”的循环，而不是简单停住。

核心目标不是“完美识别所有报错”，而是：
- 先把错误变成结构化信息
- 再用统一的修复策略处理
- 最后自动重试，直到成功或达到上限

---

## 2. 设计原则

1. 先做轻量、可落地版本
   - 不追求完美的错误推理
   - 先支持最常见的几类错误

2. 用“分类 + 统一动作”替代“逐条 case-by-case”
   - 例：依赖错误 → 检查依赖文件并安装
   - 例：语法错误 → 阅读相关文件并修复

3. 失败信息必须结构化
   - 让 Agent 的下一轮行动能基于数据而不是纯文本猜测

4. 修复要“最小化”
   - 优先做局部修复，而不是大改动

---

## 3. 需要支持的错误类型

建议先支持以下 5 类：

### 3.1 语法/解析类错误
示例：
- SyntaxError
- IndentationError
- Unexpected token

处理思路：
- 定位文件和报错行
- 读取相关代码
- 修复语法问题
- 重试

### 3.2 依赖/环境类错误
示例：
- ModuleNotFoundError
- Command not found
- No module named ...

处理思路：
- 检查 requirements.txt / pyproject.toml / package.json
- 识别缺少的依赖
- 安装依赖
- 重试

### 3.3 路径/文件类错误
示例：
- No such file or directory
- FileNotFoundError
- Cannot open file

处理思路：
- 检查目标路径是否正确
- 查看项目结构
- 修正路径或文件名
- 重试

### 3.4 测试/断言类错误
示例：
- AssertionError
- test failed
- expected X but got Y

处理思路：
- 读取测试输出
- 定位相关代码
- 修复逻辑
- 重试

### 3.5 权限/执行环境类错误
示例：
- Permission denied
- EACCES
- Access is denied

处理思路：
- 检查命令是否适合当前环境
- 需要时调整命令或提示用户权限问题

---

## 4. 统一的数据结构

错误自愈系统建议把失败信息抽象为一个结构化对象：

```python
{
    "error_type": "dependency",
    "summary": "缺少模块 pandas",
    "details": "ModuleNotFoundError: No module named 'pandas'",
    "suggested_action": "install_dependency",
    "confidence": "high"
}
```

这样后续可以直接由 Agent 基于这份结构化信息做下一步动作。

---

## 5. 推荐实现方式

### 5.1 新增一个错误分析模块
建议新增文件：
- agent/error_recovery.py

这个模块提供一个函数：

```python
classify_error(output: str) -> dict
```

它的职责是：
- 从命令输出中识别错误类型
- 输出结构化信息
- 给出下一步建议

### 5.2 在工具执行流程中接入
在 Agent 执行 run_command 后，如果失败，就触发一次错误分析。

例如：
- 命令失败
- 读取 stderr/stdout
- 调用 classify_error()
- 把结果作为“新的上下文信息”注入到后续对话中

### 5.3 让 Agent 进入修复循环
失败后，Agent 不应该直接停，而是进入一个简化循环：

1. 执行命令
2. 如果成功 → 完成
3. 如果失败 → 分析错误
4. 根据分析结果做修复
5. 重试
6. 超过次数上限 → 停止并汇总

---

## 6. 最小可用版本（建议先实现）

为了避免一开始太复杂，建议先实现下面这个版本：

### 6.1 支持的失败类型
- syntax error
- missing dependency
- file not found
- test failure

### 6.2 行为
- 只对 run_command 的失败场景生效
- 失败后自动生成一条“修复提示”
- 让 Agent 在下一轮中继续处理

例如：
- 失败后自动追加一条系统消息：
  - “上一步命令失败，请分析报错并修复后重试。”

### 6.3 反馈形式
Agent 的下一步可以是：
- 读取错误相关文件
- 查看依赖配置
- 修复代码
- 重新执行命令

这已经足够形成一个基本的错误自愈闭环。

---

## 7. 后续增强方向

在最小版本稳定后，可以继续增强：

1. 自动重试次数控制
   - 如最多 3 次

2. 失败历史记录
   - 记录每次失败原因和修复动作

3. 回滚支持
   - 失败后回到上一次 checkpoint

4. 更智能的修复建议
   - 例如根据错误类型自动选择最适合的工具

5. 任务级别的自愈
   - 不仅是单条命令失败，而是整项任务失败后继续调整

---

## 8. 推荐的落地顺序

1. 先实现错误分类器
2. 再让 Agent 在 run_command 失败时触发它
3. 再把分析结果注入下一轮上下文
4. 最后加上重试次数限制和 checkpoint 保护

---

## 9. 结论

错误自愈不需要一开始就做成“非常聪明的自动修复系统”。
最好的起点是：
- 把失败信息结构化
- 把错误归类
- 让 Agent 在下一轮自动继续分析和修复

这会比“单纯报错然后停住”强很多，也最适合你当前这个 CLI Agent 项目。