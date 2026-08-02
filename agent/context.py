"""对话历史管理：防止 token 爆炸。"""

MAX_MESSAGES = 40  # 超过后截断


def trim_messages(messages: list[dict]) -> list[dict]:
    """保留 system + 最近 N 条，中间用摘要替代。"""
    if len(messages) <= MAX_MESSAGES:
        return messages

    system = messages[0]
    recent = messages[-(MAX_MESSAGES - 2):]

    # 中间部分压缩为一条摘要
    trimmed_count = len(messages) - 1 - len(recent)
    summary_msg = {
        "role": "user",
        "content": f"[系统提示：之前已有 {trimmed_count} 条对话被省略，请基于当前上下文继续。]",
    }

    return [system, summary_msg] + recent