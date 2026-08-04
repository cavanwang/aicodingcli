# AI Coding Assistant — VS Code 扩展

聊天式 AI 编程助手，基于 Python Agent 核心 + VS Code 扩展前端。

## 前置环境

| 依赖 | 最低版本 | 检查命令 |
|---|---|---|
| Python | 3.10+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| VS Code | 1.85+ | `code --version` |

## 一、配置 Python Agent

```bash
# 进入项目根目录
cd /path/to/aicodingcli

# 创建虚拟环境（如果还没有）
python3 -m venv .venv
source .venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt

# 配置 API Key（必须）
# 编辑 .env 文件，确保包含：
# API_KEY=your-api-key-here
# BASE_URL=https://your-api-endpoint/v1
# MODEL_NAME=qwen-plus
```

验证 Agent 能正常运行：

```bash
source .venv/bin/activate
python main.py --server --workspace /path/to/your/project
# 看到 {"type": "ready", ...} 即表示正常
# 按 Ctrl+C 退出
```

## 二、编译扩展

```bash
cd vscode-extension

# 安装 npm 依赖（首次）
npm install

# 编译 TypeScript
npm run compile
```

## 三、打包 .vsix

```bash
cd vscode-extension

# 打包生成 .vsix 文件
npm run package
# 输出: aicoding-assistant-0.1.0.vsix（约 13KB）
```

## 四、安装到 VS Code

```bash
# 方式一：命令行安装
code --install-extension vscode-extension/aicoding-assistant-0.1.0.vsix

# 方式二：VS Code 内安装
# 按 Cmd+Shift+P → 输入 "Install from VSIX" → 选择 .vsix 文件
```

安装后 VS Code 左侧活动栏会出现 **AI Coding** 图标。

## 五、配置扩展

在 VS Code 设置中搜索 `aicoding`：

| 设置项 | 默认值 | 说明 |
|---|---|---|
| `aicoding.pythonPath` | `python` | Python 解释器路径。如果使用虚拟环境，填绝对路径，如 `/path/to/aicodingcli/.venv/bin/python` |
| `aicoding.projectPath` | （空） | Agent 工作目录。留空则使用当前 VS Code 打开的工作区根目录 |

**推荐配置**（使用虚拟环境）：

打开 VS Code 设置 JSON（`Cmd+Shift+P` → `Preferences: Open Settings (JSON)`），添加：

```json
{
  "aicoding.pythonPath": "/path/to/aicodingcli/.venv/bin/python",
  "aicoding.projectPath": "/path/to/your/project"
}
```

## 六、使用

1. 点击左侧活动栏 **AI Coding** 图标，打开聊天面板
2. 在底部输入框输入消息，按 Enter 发送
3. Agent 会自动感知当前编辑的文件和选中的代码
4. 支持 `@file:path/to/file.py` 引用文件内容

## 七、开发调试

```bash
cd vscode-extension

# 编译 + 监听文件变化自动重编译
npm run watch
```

然后在 VS Code 中：

1. 用 VS Code 打开 `vscode-extension/` 目录
2. 按 **F5** 启动 Extension Development Host
3. 会打开一个新的 VS Code 窗口，扩展已加载
4. 在新窗口中测试扩展功能
5. 修改代码后 `npm run watch` 会自动重编译，在 Dev Host 窗口按 `Cmd+R` 重新加载

## 八、日志排查

### VS Code 扩展侧日志

- 打开 VS Code 输出面板（`Cmd+Shift+U`）
- 右上角下拉选择 **"AI Coding"**
- 包含：扩展激活、子进程启动/退出、消息收发、错误信息

### Python Agent 日志

```bash
# Agent 核心日志（文件日志，全链路）
cat ~/.aicoding/logs/agent.log

# 执行轨迹（结构化 JSON，每次会话一个文件）
ls ~/.aicoding/traces/
```

### 常见问题

| 现象 | 排查 |
|---|---|
| 聊天面板显示"进程错误" | 检查 `aicoding.pythonPath` 是否正确指向 Python 解释器 |
| Agent 无响应 | 查看 VS Code 输出面板 "AI Coding"，检查是否有 stderr 错误 |
| API 调用失败 | 检查项目根目录 `.env` 中的 `API_KEY` 和 `BASE_URL` |
| 工具执行权限问题 | 检查 `aicoding.projectPath` 是否指向正确的工作目录 |
