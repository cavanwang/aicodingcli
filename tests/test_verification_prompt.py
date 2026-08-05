"""任务 E（验证驱动理解）prompt 引导测试。

E1/E2 通过 SYSTEM_PROMPT 引导实现，此处保障关键方法论段落
不被后续修改意外删除。端到端效果由人工验收（真实对话验证）。
"""

import config


class TestVerificationDrivenPrompt:
    """E1: 假设-验证方法论必须在 SYSTEM_PROMPT 中。"""

    def test_hypothesis_section_exists(self):
        assert "假设-验证方法" in config.SYSTEM_PROMPT

    def test_when_to_verify(self):
        # 何时必须验证的典型场景
        assert "边界行为" in config.SYSTEM_PROMPT

    def test_minimal_verification_example(self):
        # 最小验证的可执行示例
        assert "python -c" in config.SYSTEM_PROMPT

    def test_correction_loop(self):
        # 验证失败必须修正理解，不在错误假设上继续
        assert "修正理解" in config.SYSTEM_PROMPT

    def test_no_guessing_words(self):
        # 禁止未验证的模糊表述
        assert "应该" in config.SYSTEM_PROMPT and "大概" in config.SYSTEM_PROMPT


class TestAutoAccumulationPrompt:
    """E2: 探索成果自动沉淀引导必须在 SYSTEM_PROMPT 中。"""

    def test_accumulation_section_exists(self):
        assert "探索成果自动沉淀" in config.SYSTEM_PROMPT

    def test_proactive_append(self):
        # 主动 append、不等用户要求
        assert "save_memory(action='append')" in config.SYSTEM_PROMPT
        assert "不必等用户要求" in config.SYSTEM_PROMPT

    def test_fact_categories(self):
        # 四类沉淀事实
        for keyword in ("隐含耦合", "环境怪癖", "踩坑记录"):
            assert keyword in config.SYSTEM_PROMPT

    def test_quality_principle(self):
        # 只沉淀跨会话有价值的事实
        assert "跨会话" in config.SYSTEM_PROMPT
