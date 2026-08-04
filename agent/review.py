"""变更审查模块：自动审查代码变更质量，生成结构化报告。

整合 analyze_changes 和 verify_changes 的结果，
评估风险等级并给出改进建议。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import config
from agent.tools.git_ops import analyze_changes, git_diff


@dataclass
class ReviewResult:
    """审查结果数据。"""
    files_changed: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    tests_found: list[str] = field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    test_output: str = ""
    risk_level: str = "low"           # low | medium | high
    suggestions: list[str] = field(default_factory=list)
    raw_analysis: str = ""

    def to_json(self) -> str:
        """序列化为 JSON 字符串。"""
        data = asdict(self)
        # 截断过长的 test_output
        if len(data.get("test_output", "")) > 500:
            data["test_output"] = data["test_output"][:500] + "...(truncated)"
        # 截断 raw_analysis
        if len(data.get("raw_analysis", "")) > 1000:
            data["raw_analysis"] = data["raw_analysis"][:1000] + "...(truncated)"
        return json.dumps(data, ensure_ascii=False, indent=2)


class ChangeReviewer:
    """变更审查器：分析变更、运行测试、评估风险。"""

    def review(self) -> ReviewResult:
        """执行一次完整审查。"""
        result = ReviewResult()

        # 1. 分析变更范围
        analysis = analyze_changes()
        result.raw_analysis = analysis

        if "当前无未提交变更" in analysis:
            result.suggestions.append("当前无变更，无需审查")
            return result

        # 解析变更文件
        result.files_changed = self._parse_changed_files(analysis)
        stats = self._parse_stats(analysis)
        result.lines_added = stats.get("additions", 0)
        result.lines_removed = stats.get("deletions", 0)

        # 2. 查找并运行测试
        test_info = self._find_and_run_tests(result.files_changed)
        result.tests_found = test_info.get("test_files", [])
        result.tests_passed = test_info.get("passed", 0)
        result.tests_failed = test_info.get("failed", 0)
        result.test_output = test_info.get("output", "")

        # 3. 评估风险
        result.risk_level = self._assess_risk(result)

        # 4. 生成建议
        result.suggestions = self._generate_suggestions(result)

        return result

    def format_report(self, result: ReviewResult) -> str:
        """格式化审查报告。"""
        if not result.files_changed and not result.raw_analysis:
            return "📋 审查报告：当前无变更"

        if not result.files_changed:
            return f"📋 审查报告\n\n{result.raw_analysis}"

        lines = ["📋 变更审查报告", "=" * 40]

        # 变更概览
        lines.append(f"\n📁 变更文件: {len(result.files_changed)} 个")
        for f in result.files_changed:
            lines.append(f"  - {f}")

        lines.append(f"\n📊 行数统计: +{result.lines_added} / -{result.lines_removed}")

        # 测试结果
        if result.tests_found:
            lines.append(f"\n🧪 测试文件: {len(result.tests_found)} 个")
            for t in result.tests_found:
                lines.append(f"  - {t}")
            lines.append(f"\n✅ 通过: {result.tests_passed}  ❌ 失败: {result.tests_failed}")
        else:
            lines.append("\n⚠️  未找到相关测试")

        # 风险评估
        risk_icons = {"low": "🟢", "medium": "🟡", "high": "🔴"}
        risk_labels = {"low": "低风险", "medium": "中风险", "high": "高风险"}
        icon = risk_icons.get(result.risk_level, "?")
        label = risk_labels.get(result.risk_level, "未知")
        lines.append(f"\n{icon} 风险等级: {label}")

        # 建议
        if result.suggestions:
            lines.append("\n💡 建议:")
            for s in result.suggestions:
                lines.append(f"  - {s}")

        return "\n".join(lines)

    # ── 内部方法 ──

    def _parse_changed_files(self, analysis: str) -> list[str]:
        """从分析结果中提取变更文件列表。"""
        files = []
        for line in analysis.split("\n"):
            line = line.strip()
            # 匹配 "M  path/to/file" 或 "A  path/to/file" 格式
            if len(line) >= 3 and line[:2] in ("M ", " M", "A ", "??", "R "):
                file_path = line[2:].strip()
                if file_path and not file_path.endswith("/"):
                    files.append(file_path)
        return files

    def _parse_stats(self, analysis: str) -> dict[str, int]:
        """从分析结果中提取行数统计。"""
        stats = {"additions": 0, "deletions": 0}
        for line in analysis.split("\n"):
            if "新增" in line or "+" in line:
                # 尝试提取数字
                import re
                match = re.search(r"(\d+)\s*(?:行|lines?)?\s*(?:新增|additions?)", line, re.IGNORECASE)
                if match:
                    stats["additions"] = int(match.group(1))
            if "删除" in line or "-" in line:
                import re
                match = re.search(r"(\d+)\s*(?:行|lines?)?\s*(?:删除|deletions?)", line, re.IGNORECASE)
                if match:
                    stats["deletions"] = int(match.group(1))
        return stats

    def _find_and_run_tests(self, changed_files: list[str]) -> dict[str, Any]:
        """查找相关测试并运行。"""
        result = {
            "test_files": [],
            "passed": 0,
            "failed": 0,
            "output": "",
        }

        tests_dir = config.WORKSPACE_DIR / "tests"
        if not tests_dir.exists():
            return result

        # 查找相关测试文件
        test_files = []
        for cf in changed_files:
            name = Path(cf).stem
            candidate = tests_dir / f"test_{name}.py"
            if candidate.exists():
                test_files.append(str(candidate.relative_to(config.WORKSPACE_DIR)))

        result["test_files"] = test_files
        if not test_files:
            return result

        # 运行测试
        try:
            test_paths = " ".join(test_files)
            proc = subprocess.run(
                f"python -m pytest {test_paths} -v --tb=short",
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(config.WORKSPACE_DIR),
            )
            output = proc.stdout + proc.stderr
            result["output"] = output[:3000] if len(output) > 3000 else output

            # 解析测试结果
            import re
            passed_match = re.search(r"(\d+) passed", output)
            failed_match = re.search(r"(\d+) failed", output)
            if passed_match:
                result["passed"] = int(passed_match.group(1))
            if failed_match:
                result["failed"] = int(failed_match.group(1))
        except subprocess.TimeoutExpired:
            result["output"] = "测试执行超时（60秒）"
        except Exception as e:
            result["output"] = f"测试执行失败: {e}"

        return result

    def _assess_risk(self, result: ReviewResult) -> str:
        """评估变更风险。"""
        # 高风险条件
        if result.tests_failed > 0:
            return "high"
        if len(result.files_changed) > 10:
            return "high"
        if result.lines_added + result.lines_removed > 500:
            return "high"

        # 中风险条件
        if not result.tests_found and len(result.files_changed) > 3:
            return "medium"
        if result.lines_added + result.lines_removed > 200:
            return "medium"

        # 核心文件变更
        core_patterns = {"core.py", "config.py", "registry.py", "main.py"}
        for f in result.files_changed:
            if Path(f).name in core_patterns:
                return "medium"

        return "low"

    def _generate_suggestions(self, result: ReviewResult) -> list[str]:
        """生成改进建议。"""
        suggestions = []

        if result.tests_failed > 0:
            suggestions.append(f"有 {result.tests_failed} 个测试失败，请修复后再提交")

        if not result.tests_found and result.files_changed:
            suggestions.append("变更文件缺少对应测试，建议补充测试用例")

        if len(result.files_changed) > 5:
            suggestions.append(f"本次变更涉及 {len(result.files_changed)} 个文件，建议分拆为更小的提交")

        if result.lines_added > 200:
            suggestions.append("新增代码较多，建议检查是否有可复用的现有逻辑")

        core_patterns = {"core.py", "config.py"}
        for f in result.files_changed:
            if Path(f).name in core_patterns:
                suggestions.append(f"核心文件 {f} 被修改，请仔细审查")
                break

        if not suggestions:
            suggestions.append("变更范围合理，建议提交前做最终验证")

        return suggestions
