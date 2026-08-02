"""代码搜索工具。"""

import subprocess
import config


def search_in_files(keyword: str, file_pattern: str = "*") -> str:
    """在工作目录中搜索关键词（类似 grep -rn）。"""
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include", file_pattern, keyword, "."],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(config.WORKSPACE_DIR),
        )
        output = result.stdout.strip()
        if not output:
            return f"未找到 '{keyword}'"
        if len(output) > config.MAX_COMMAND_OUTPUT_CHARS:
            output = output[: config.MAX_COMMAND_OUTPUT_CHARS] + "\n... (截断)"
        return output
    except Exception as e:
        return f"搜索失败: {e}"
