"""Git 操作工具。"""

import re
import subprocess
from pathlib import Path
import config


def _git(args: str) -> str:
    try:
        result = subprocess.run(
            f"git {args}",
            shell=True, capture_output=True, text=True,
            timeout=15, cwd=str(config.WORKSPACE_DIR),
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > config.MAX_COMMAND_OUTPUT_CHARS:
            output = output[:config.MAX_COMMAND_OUTPUT_CHARS] + "\n...(截断)"
        return output or "(无输出)"
    except Exception as e:
        return f"git 执行失败: {e}"


def git_diff(file_path: str = "") -> str:
    """查看当前未提交的改动。可按文件过滤。"""
    if file_path:
        return _git(f"diff -- {file_path}")
    return _git("diff")


def git_log(count: int = 10) -> str:
    """查看最近 N 条提交记录。"""
    return _git(f"log --oneline -{count}")


def git_status() -> str:
    """查看工作区状态。"""
    return _git("status --short")


def git_checkpoint(message: str = "auto-checkpoint") -> str:
    """自动提交当前状态，作为回滚点。"""
    _git("add -A")
    result = _git(f'commit -m "[agent] {message}" --allow-empty')
    if "nothing to commit" in result:
        return "(无变更，跳过 checkpoint)"
    return f"✅ checkpoint 已创建: {message}"


def git_rollback() -> str:
    """回滚到上一 checkpoint（丢弃工作区改动）。"""
    # 先确认有上一个提交
    log = _git("log --oneline -2")
    if log.count("\n") < 1:
        return "❌ 没有可回滚的历史提交"

    _git("checkout HEAD~1 -- .")
    _git("add -A")
    _git('commit -m "[agent] rollback" --allow-empty')
    return "✅ 已回滚到上一 checkpoint"


# ──────────────────────────────────────────────
# 差异分析工具
# ──────────────────────────────────────────────


def analyze_changes() -> str:
    """分析当前未提交变更的影响范围。

    返回：变更文件列表、变更类型（新增/修改/删除）、行数统计。
    """
    # 获取简短状态
    status_output = _git("status --porcelain")
    if status_output == "(无输出)":
        return "当前无未提交变更"

    lines = status_output.strip().split("\n")
    files_info = []
    total_additions = 0
    total_deletions = 0

    for line in lines:
        if len(line) < 3:
            continue
        status_code = line[:2]
        file_path = line[2:].strip()

        # 解析状态码
        if status_code == "??":
            change_type = "新增(未跟踪)"
        elif status_code == "A ":
            change_type = "新增(已暂存)"
        elif status_code in ("M ", " M"):
            change_type = "修改"
        elif status_code in ("D ", " D"):
            change_type = "删除"
        elif status_code == "R ":
            change_type = "重命名"
        else:
            change_type = f"变更({status_code.strip()})"

        # 获取该文件的 diff 统计
        if change_type not in ("新增(未跟踪)", "删除"):
            diff_stat = _git(f"diff --numstat -- {file_path}")
            if diff_stat != "(无输出)" and diff_stat and not diff_stat.startswith("git 执行失败"):
                parts = diff_stat.split()
                if len(parts) >= 2:
                    try:
                        additions = int(parts[0]) if parts[0] != "-" else 0
                        deletions = int(parts[1]) if parts[1] != "-" else 0
                        total_additions += additions
                        total_deletions += deletions
                    except ValueError:
                        pass

        files_info.append(f"  [{change_type}] {file_path}")

    result = ["## 变更分析", ""]
    result.append(f"变更文件数: {len(files_info)}")
    result.append(f"新增行数: {total_additions}")
    result.append(f"删除行数: {total_deletions}")
    result.append("")
    result.append("文件列表:")
    result.extend(files_info)

    return "\n".join(result)


def _git_co_occurrence(file_path: str, max_commits: int = 100) -> list[tuple[str, int]]:
    """统计 git 历史中与目标文件经常一起提交的文件（共现权重）。

    返回 [(文件路径, 共现提交次数)]，按次数降序，不含目标文件自身。
    注意：不能用 pathspec 过滤（会使 --name-only 只输出匹配文件），
    改为列出全部提交文件后在本地过滤包含目标的提交。
    """
    path = file_path.lstrip("./") or file_path
    output = _git(f"log -{max_commits} --name-only --pretty=format:'###COMMIT'")
    if output == "(无输出)" or output.startswith("git 执行失败"):
        return []

    counts: dict[str, int] = {}
    for block in output.split("###COMMIT"):
        files = {
            ln.strip() for ln in block.splitlines()
            if ln.strip() and not ln.strip().startswith(("fatal:", "error:"))
        }
        if path not in files:
            continue  # 只统计包含目标文件的提交
        for f in files - {path}:
            counts[f] = counts.get(f, 0) + 1

    return sorted(counts.items(), key=lambda kv: -kv[1])


def get_related_files(file_path: str) -> str:
    """查找与指定文件相关的其他文件：引用关系 + git 共现历史。

    用于评估修改影响范围：如果修改了 X，哪些文件可能需要一起改。
    共现权重：git 历史中经常一起提交的文件，往往存在隐含耦合。
    """
    target = Path(file_path)
    if not target.suffix:
        return "请指定具体文件路径（需含扩展名）"

    # 提取模块名（不含扩展名）
    module_name = target.stem
    suffix = target.suffix

    # 根据文件类型确定搜索模式
    if suffix in (".py",):
        # Python: 搜索 import 和 from ... import
        patterns = [
            f"import.*{module_name}",
            f"from.*{module_name}",
        ]
        search_glob = "*.py"
    elif suffix in (".js", ".ts", ".jsx", ".tsx"):
        # JS/TS: 搜索 import 和 require
        patterns = [
            f"import.*{module_name}",
            f"require.*{module_name}",
            f"from.*{module_name}",
        ]
        search_glob = "*.js"
        search_glob2 = "*.ts"
    else:
        # 通用：搜索文件名
        patterns = [module_name]
        search_glob = "*"

    results = []
    globs = [search_glob]
    if suffix in (".js", ".ts", ".jsx", ".tsx"):
        globs = ["*.js", "*.ts", "*.jsx", "*.tsx"]
    for pattern in patterns:
        for g in globs:
            output = _git(f"grep -n '{pattern}' -- '{g}'")
            if output != "(无输出)" and not output.startswith("git 执行失败"):
                results.append(output)

    # 提取引用文件去重
    related_files = set()
    for r in results:
        for line in r.split("\n"):
            line = line.strip()
            if line and not line.startswith("Binary"):
                # git grep -n 输出格式: file:line:content
                match = re.match(r'^([^:]+):', line)
                if match:
                    related_files.add(match.group(1))
    related_files.discard(file_path.lstrip("./"))

    # git 共现历史
    co_occurred = _git_co_occurrence(file_path)

    if not related_files and not co_occurred:
        return f"未找到与 '{module_name}' 相关的文件（无引用、无 git 共现记录）"

    out = [f"## 与 '{file_path}' 相关的文件", ""]
    if related_files:
        out.append("### 引用关系（import/require）")
        for f in sorted(related_files):
            out.append(f"  - {f}")
        out.append("")
    if co_occurred:
        out.append("### git 共现历史（经常一起修改，隐含耦合风险高）")
        for f, cnt in co_occurred[:10]:
            out.append(f"  - {f}（同提交 {cnt} 次）")
        out.append("")
    both = sorted(related_files & {f for f, _ in co_occurred})
    if both:
        out.append(f"⚠️ 同时命中引用与共现，修改时优先检查: {', '.join(both)}")
    else:
        out.append(f"共 {len(related_files)} 个引用文件、{len(co_occurred)} 个共现文件")

    return "\n".join(out)
