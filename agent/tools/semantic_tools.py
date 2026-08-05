"""语义搜索工具：自然语言 → 代码的语义检索（Phase 11 任务 C）。"""

from agent.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TOP_K = 5
_DEFAULT_THRESHOLD = 0.30


def semantic_search(query: str, top_k: int = _DEFAULT_TOP_K) -> str:
    """用自然语言语义检索代码（如"分页处理逻辑"、"用户登录失败处理"）。

    基于 AST 函数/类级分块 + embedding 向量相似度，支持中英跨模态查询。
    首次调用会构建索引（仅嵌入变更文件，后续增量更新）。

    Args:
        query: 自然语言查询或符号描述
        top_k: 返回结果数量上限，默认 5
    """
    if not query or not query.strip():
        return "错误: query 不能为空"
    top_k = max(1, min(int(top_k or _DEFAULT_TOP_K), 20))

    # 延迟导入，避免未使用时引入 numpy/openai 开销
    from agent.semantic import EmbeddingAPIError, SemanticIndex

    try:
        index = SemanticIndex()
        stats = index.update()
    except EmbeddingAPIError as e:
        logger.warning("[语义搜索] embedding API 不可用，降级提示: %s", e)
        return (
            f"语义搜索暂不可用（embedding API 错误: {e}）。\n"
            "请降级使用关键词工具：search_in_files（内容搜索）、"
            "find_files（文件名定位）、find_definition（符号定义）。"
        )
    except Exception as e:  # 索引构建的其他异常（如权限问题）
        logger.error("[语义搜索] 索引构建失败: %s", e)
        return f"语义索引构建失败: {e}\n请降级使用 search_in_files 关键词搜索。"

    if not index.chunks:
        return "项目内无可索引的 Python 代码 chunk。请改用 search_in_files 关键词搜索。"

    try:
        results = index.search(query, top_k=top_k, threshold=_DEFAULT_THRESHOLD)
    except EmbeddingAPIError as e:
        return (
            f"查询嵌入失败（embedding API 错误: {e}）。\n"
            "请降级使用 search_in_files 关键词搜索。"
        )

    if not results:
        return (
            f"未找到与 '{query}' 语义相关的代码（阈值 {_DEFAULT_THRESHOLD}）。\n"
            "建议：换更具体的描述重试，或用 search_in_files 做关键词搜索。"
        )

    lines = [f"语义搜索结果（query='{query}'，索引: {len(index.chunks)} chunks"
             + (f"，本次更新 {stats['added']} 文件" if stats["added"] else "") + "）:"]
    for r in results:
        lines.append(f"  [{r['score']}] {r['file']}:{r['line']}  ({r['kind']}) {r['sig']}")
    lines.append("提示: 用 read_file 读取命中位置的上下文确认。")
    return "\n".join(lines)
