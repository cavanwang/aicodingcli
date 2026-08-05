"""语义搜索测试（Phase 11 任务 C）。

单元测试全部使用确定性 mock 嵌入（不依赖真实 API），
真实 API 的端到端验证单独在 TestLiveAPI 中（无 API key 时自动跳过）。
"""

import hashlib
import json
from unittest.mock import MagicMock

import pytest

import config
from agent.semantic import (
    EmbeddingAPIError,
    SemanticIndex,
    chunk_python_source,
)


# ──────────────────────────────────────────────
# Mock 嵌入器：按文本中的关键词生成确定性向量（可区分语义）
# ──────────────────────────────────────────────
_KEYWORDS = ["分页", "paginate", "page", "登录", "login", "auth",
             "日志", "logger", "加密", "hash"]


class FakeEmbedder:
    """确定性 mock：每个关键词一维，词频作为分量。"""

    model = "fake-model"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.call_count = 0

    def embed(self, texts):
        self.call_count += 1
        if self.fail:
            raise EmbeddingAPIError("mock API down")
        vecs = []
        for t in texts:
            low = t.lower()
            vec = [float(low.count(k)) for k in _KEYWORDS]
            # 末位为独立"无关维度"：无关键词时置 1，避免与真实语义产生虚假相似度
            vec.append(0.0 if any(v > 0 for v in vec) else 1.0)
            vecs.append(vec)
        return vecs


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """构造含分页/登录/日志三类代码的测试项目。"""
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)

    (tmp_path / "pagination.py").write_text(
        "def paginate(items, page, page_size):\n"
        "    # 分页处理：按页码切片\n"
        "    return items[page * page_size:(page + 1) * page_size]\n\n"
        "class Pager:\n"
        "    def next_page(self):\n"
        "        return paginate([], 0, 10)\n"
    )
    (tmp_path / "auth.py").write_text(
        "def handle_login_failure(user):\n"
        "    # 登录失败处理 auth login\n"
        "    return False\n"
    )
    (tmp_path / "logging_setup.py").write_text(
        "import logging\n\n"
        "def setup_logger(name):\n"
        "    return logging.getLogger(name)\n"
    )
    return tmp_path


def make_index(workspace, fail: bool = False) -> SemanticIndex:
    return SemanticIndex(
        workspace=workspace,
        index_path=workspace / ".cache" / "semantic" / "index.json",
        embedder=FakeEmbedder(fail=fail),
    )


# ──────────────────────────────────────────────
# C1: AST 分块
# ──────────────────────────────────────────────
class TestChunking:
    def test_function_and_class_chunks(self):
        src = ("def paginate(items, page):\n    return items\n\n"
               "class Pager:\n    def go(self):\n        pass\n")
        chunks = chunk_python_source(src, "x.py")
        names = {c.name for c in chunks}
        assert "paginate" in names and "Pager" in names

    def test_module_chunk_for_imports(self):
        chunks = chunk_python_source("import os\nMAX = 3\n\ndef f():\n    pass\n", "x.py")
        kinds = {c.kind for c in chunks}
        assert "module" in kinds and "function" in kinds

    def test_syntax_error_fallback(self):
        chunks = chunk_python_source("def broken(:\n", "x.py")
        assert len(chunks) >= 1 and chunks[0].name == "<module>"

    def test_long_function_split(self):
        body = "\n".join(f"    x{i} = {i}" for i in range(800))
        src = f"def big():\n{body}\n"
        chunks = chunk_python_source(src, "x.py")
        big_parts = [c for c in chunks if c.name.startswith("big")]
        assert len(big_parts) > 1  # 超长函数被切分


# ──────────────────────────────────────────────
# C3: 增量索引
# ──────────────────────────────────────────────
class TestIncrementalIndex:
    def test_first_build(self, workspace):
        idx = make_index(workspace)
        stats = idx.update()
        assert stats["added"] == 3
        assert len(idx.chunks) > 0

    def test_no_change_no_reembed(self, workspace):
        idx = make_index(workspace)
        idx.update()
        calls_first = idx.embedder.call_count
        # 重新加载索引，无变更时不应再调 embedding
        idx2 = make_index(workspace)
        stats = idx2.update()
        assert stats["added"] == 0
        assert idx2.embedder.call_count == 0
        assert len(idx2.chunks) == len(idx.chunks)

    def test_changed_file_reembedded(self, workspace):
        idx = make_index(workspace)
        idx.update()
        before = len(idx.chunks)
        (workspace / "auth.py").write_text(
            "def handle_login_failure(user):\n    return True\n"
            "def logout():\n    pass\n"
        )
        idx2 = make_index(workspace)
        stats = idx2.update()
        assert stats["added"] == 1
        auth_chunks = [c for c in idx2.chunks if c["file"] == "auth.py"]
        assert any(c["name"] == "logout" for c in auth_chunks)

    def test_deleted_file_removed(self, workspace):
        idx = make_index(workspace)
        idx.update()
        (workspace / "logging_setup.py").unlink()
        idx2 = make_index(workspace)
        stats = idx2.update()
        assert stats["removed"] == 1
        assert not any(c["file"] == "logging_setup.py" for c in idx2.chunks)

    def test_index_persistence_format(self, workspace):
        idx = make_index(workspace)
        idx.update()
        data = json.loads(idx.index_path.read_text())
        assert data["version"] == 1
        assert data["model"] == "fake-model"
        # 哈希与文件内容一致
        content = (workspace / "auth.py").read_text()
        assert data["files"]["auth.py"] == hashlib.sha256(content.encode()).hexdigest()

    def test_corrupted_index_rebuilds(self, workspace):
        idx = make_index(workspace)
        idx.update()
        idx.index_path.write_text("{bad json")
        idx2 = make_index(workspace)
        stats = idx2.update()
        assert stats["added"] == 3  # 全量重建


# ──────────────────────────────────────────────
# 检索（10 个查询场景）
# ──────────────────────────────────────────────
class TestSearchQueries:
    @pytest.fixture(autouse=True)
    def build(self, workspace):
        self.idx = make_index(workspace)
        self.idx.update()

    def _files(self, query, top_k=3):
        return [r["file"] for r in self.idx.search(query, top_k=top_k, threshold=0.0)]

    def test_query_01_pagination_cn(self):
        assert self._files("分页处理逻辑")[0] == "pagination.py"

    def test_query_02_pagination_en(self):
        assert self._files("paginate items by page size")[0] == "pagination.py"

    def test_query_03_login_failure(self):
        assert self._files("用户登录失败处理")[0] == "auth.py"

    def test_query_04_auth_login(self):
        assert self._files("auth login failure handler")[0] == "auth.py"

    def test_query_05_logger(self):
        assert self._files("日志 logger 初始化")[0] == "logging_setup.py"

    def test_query_06_next_page_method(self):
        results = self.idx.search("next_page 翻页方法", top_k=3, threshold=0.0)
        assert any(r["name"] == "Pager" for r in results)

    def test_query_07_threshold_filters(self):
        # 完全无关查询 + 严格阈值应无结果
        results = self.idx.search("zzz qqq 完全不相关", top_k=5, threshold=10.0)
        assert results == []

    def test_query_08_topk_limit(self):
        results = self.idx.search("page", top_k=2, threshold=0.0)
        assert len(results) <= 2

    def test_query_09_result_fields(self):
        results = self.idx.search("分页", top_k=1, threshold=0.0)
        r = results[0]
        assert {"file", "name", "kind", "line", "sig", "score"} <= set(r.keys())
        assert isinstance(r["line"], int) and r["line"] >= 1

    def test_query_10_scores_sorted_desc(self):
        results = self.idx.search("page paginate", top_k=5, threshold=0.0)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)


# ──────────────────────────────────────────────
# C4: 工具层降级与输出
# ──────────────────────────────────────────────
class TestToolFallback:
    def test_api_failure_degrades(self, workspace, monkeypatch):
        from agent.tools import semantic_tools
        import agent.semantic as sem

        orig = sem.SemanticIndex

        class BrokenIndex(orig):
            def __init__(self, *a, **kw):
                kw.setdefault("workspace", workspace)
                kw.setdefault("index_path", workspace / ".cache" / "x.json")
                kw.setdefault("embedder", FakeEmbedder(fail=True))
                super().__init__(*a, **kw)

        monkeypatch.setattr(sem, "SemanticIndex", BrokenIndex)
        out = semantic_tools.semantic_search("分页逻辑")
        assert "降级" in out and "search_in_files" in out
        monkeypatch.setattr(sem, "SemanticIndex", orig)

    def test_empty_query(self, workspace):
        from agent.tools.semantic_tools import semantic_search
        assert "错误" in semantic_search("  ")

    def test_registered(self):
        from agent.tools.registry import _REGISTRY, CONFIRM_TOOLS
        names = {i["schema"]["name"] for i in _REGISTRY}
        assert "semantic_search" in names
        assert "semantic_search" not in CONFIRM_TOOLS


# ──────────────────────────────────────────────
# 真实 API 端到端（可选，无 key 时跳过）
# ──────────────────────────────────────────────
@pytest.mark.skipif(not config.API_KEY, reason="无 API key，跳过真实 API 测试")
class TestLiveAPI:
    def test_embedding_api_available(self):
        from agent.semantic import Embedder
        emb = Embedder()
        vecs = emb.embed(["分页处理逻辑", "def paginate(x): pass"])
        assert len(vecs) == 2 and len(vecs[0]) > 0
