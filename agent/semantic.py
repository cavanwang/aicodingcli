"""语义搜索核心：AST 分块 + API 嵌入 + 内容哈希增量索引。

技术路线（Phase 11 任务 C）：
- 分块粒度：AST 函数/类级别（避免整文件截断导致大文件后半部分检索不到）
- 嵌入模型：DashScope text-embedding-v3（OpenAI 兼容端点，中英跨模态）
- 增量策略：文件内容 sha256 哈希缓存，仅重新嵌入变更文件
- 检索：numpy 余弦相似度 top-k（千级 chunk 规模无需 FAISS）
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from openai import OpenAI

import config
from agent.logger import get_logger
from agent.memory import _is_ignored_dir, _is_ignored_file

logger = get_logger(__name__)

_INDEX_VERSION = 1
_BATCH_SIZE = 10          # DashScope embedding 单次批量上限
_MAX_CHUNK_CHARS = 4000   # 单 chunk 字符上限（约 < 2048 token）


# ============================================================
# C1: AST 函数/类级分块
# ============================================================

@dataclass
class CodeChunk:
    """一个可嵌入的代码片段（函数/类/模块级代码块）。"""
    file: str        # 相对 workspace 路径
    name: str        # 符号名或 "<module>"
    kind: str        # function / class / module
    line: int        # 起始行号（1-indexed）
    sig: str         # 首行签名（用于结果展示）
    text: str        # 实际代码文本


def _split_by_lines(text: str, max_chars: int) -> list[str]:
    """超长文本按行窗口切分。"""
    lines = text.splitlines(keepends=True)
    parts: list[str] = []
    buf = ""
    for line in lines:
        if len(buf) + len(line) > max_chars and buf:
            parts.append(buf)
            buf = ""
        buf += line
    if buf.strip():
        parts.append(buf)
    return parts


def chunk_python_source(source: str, rel_path: str) -> list[CodeChunk]:
    """将 Python 源码按 AST 切分为函数/类级 chunk。

    - 顶层函数/异步函数/类各为一个 chunk（类包含其全部方法）
    - 其余顶层语句（import、常量等）归入 "<module>" chunk
    - 超长 chunk 按行窗口二次切分
    - 语法错误时退化为整文件按行窗口切分
    """
    lines = source.splitlines(keepends=True)

    def seg(node: ast.AST) -> str:
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        return "".join(lines[start:end])

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [
            CodeChunk(rel_path, "<module>", "module", i * 100 + 1,
                      f"# {rel_path} (片段 {i + 1})", part)
            for i, part in enumerate(_split_by_lines(source, _MAX_CHUNK_CHARS))
        ]

    chunks: list[CodeChunk] = []
    module_parts: list[str] = []
    handled_ids: set[int] = set()

    for node in tree.body:  # 仅顶层节点
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "function"
        elif isinstance(node, ast.ClassDef):
            kind = "class"
        else:
            text = seg(node).strip()
            if text:
                module_parts.append(text)
            continue
        handled_ids.add(id(node))
        text = seg(node)
        first_line = text.splitlines()[0].strip() if text.strip() else node.name
        if len(text) <= _MAX_CHUNK_CHARS:
            chunks.append(CodeChunk(rel_path, node.name, kind, node.lineno, first_line, text))
        else:
            for i, part in enumerate(_split_by_lines(text, _MAX_CHUNK_CHARS)):
                name = node.name if i == 0 else f"{node.name}#part{i + 1}"
                chunks.append(CodeChunk(rel_path, name, kind, node.lineno, first_line, part))

    module_text = "\n\n".join(module_parts).strip()
    if module_text:
        for i, part in enumerate(_split_by_lines(module_text, _MAX_CHUNK_CHARS)):
            name = "<module>" if i == 0 else f"<module>#part{i + 1}"
            chunks.append(CodeChunk(rel_path, name, "module", 1,
                                    f"# {rel_path} 模块级代码", part))

    return chunks


# ============================================================
# C2: API 嵌入引擎
# ============================================================

class EmbeddingAPIError(Exception):
    """embedding API 调用失败（触发降级）。"""


class Embedder:
    """基于 OpenAI 兼容端点的批量嵌入引擎。"""

    def __init__(self, model: str | None = None):
        self.model = model or getattr(config, "EMBEDDING_MODEL", "text-embedding-v3")
        self._client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入，自动分批；整体失败抛出 EmbeddingAPIError。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i:i + _BATCH_SIZE]
            try:
                resp = self._client.embeddings.create(model=self.model, input=batch)
                vectors.extend(d.embedding for d in resp.data)
            except Exception as e:
                logger.error("[语义索引] embedding 调用失败: %s", e)
                raise EmbeddingAPIError(str(e)) from e
        return vectors


# ============================================================
# C3: 内容哈希增量索引
# ============================================================

def _iter_py_files(root: Path):
    """遍历 workspace 内未被忽略的 .py 文件（全路径层级过滤）。"""
    for py_file in root.rglob("*.py"):
        if not py_file.is_file():
            continue
        if _is_ignored_file(py_file.name):
            continue
        rel = py_file.relative_to(root)
        if any(_is_ignored_dir(part) for part in rel.parts[:-1]):
            continue
        yield py_file, str(rel)


class SemanticIndex:
    """语义向量索引：sha256 哈希驱动的增量构建与检索。"""

    def __init__(self, workspace: Path | None = None,
                 index_path: Path | None = None,
                 embedder: Embedder | None = None):
        self.workspace = (workspace or config.WORKSPACE_DIR).resolve()
        self.index_path = index_path or (self.workspace / ".cache" / "semantic" / "index.json")
        self.embedder = embedder or Embedder()
        self.file_hashes: dict[str, str] = {}
        self.chunks: list[dict] = []
        self._load()

    # ── 持久化 ──────────────────────────────────
    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if data.get("version") != _INDEX_VERSION:
                return  # 版本不匹配视为无效，重建
            if data.get("model") != self.embedder.model:
                return  # 模型变更需全量重建
            self.file_hashes = data.get("files", {})
            self.chunks = data.get("chunks", [])
        except (json.JSONDecodeError, OSError):
            logger.warning("[语义索引] 索引文件损坏，将重建")

    def save(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _INDEX_VERSION,
            "model": self.embedder.model,
            "files": self.file_hashes,
            "chunks": self.chunks,
        }
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.index_path)

    # ── 增量构建 ────────────────────────────────
    def update(self) -> dict:
        """增量更新索引，返回统计 {added, removed, unchanged}。"""
        current: dict[str, str] = {}
        for py_file, rel in _iter_py_files(self.workspace):
            try:
                content = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            current[rel] = hashlib.sha256(content.encode("utf-8")).hexdigest()

        changed = [r for r, h in current.items() if self.file_hashes.get(r) != h]
        removed = [r for r in self.file_hashes if r not in current]

        if not changed and not removed:
            return {"added": 0, "removed": 0, "unchanged": len(current)}

        # 移除已删除/变更文件的旧 chunk
        drop = set(changed) | set(removed)
        self.chunks = [c for c in self.chunks if c["file"] not in drop]

        # 为变更文件重新分块并嵌入
        for rel in changed:
            source = (self.workspace / rel).read_text(encoding="utf-8")
            file_chunks = chunk_python_source(source, rel)
            if not file_chunks:
                continue
            vectors = self.embedder.embed([c.text for c in file_chunks])
            for ck, vec in zip(file_chunks, vectors):
                self.chunks.append({
                    "file": ck.file, "name": ck.name, "kind": ck.kind,
                    "line": ck.line, "sig": ck.sig,
                    "vec": [round(float(x), 5) for x in vec],
                })

        self.file_hashes = current
        self.save()
        logger.info("[语义索引] 更新完成: 新增/变更 %d 文件, 删除 %d 文件, chunk 总数 %d",
                    len(changed), len(removed), len(self.chunks))
        return {"added": len(changed), "removed": len(removed),
                "unchanged": len(current) - len(changed)}

    # ── 检索 ────────────────────────────────────
    def search(self, query: str, top_k: int = 5,
               threshold: float = 0.30) -> list[dict]:
        """返回按相似度降序的结果 [{file, name, kind, line, sig, score}]。"""
        if not self.chunks:
            return []
        qvec = np.asarray(self.embedder.embed([query])[0], dtype=np.float32)
        matrix = np.asarray([c["vec"] for c in self.chunks], dtype=np.float32)
        # 余弦相似度
        qn = qvec / (np.linalg.norm(qvec) + 1e-9)
        mn = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
        scores = mn @ qn
        order = np.argsort(-scores)[:top_k]
        results = []
        for idx in order:
            score = float(scores[idx])
            if score < threshold:
                continue
            c = self.chunks[int(idx)]
            results.append({
                "file": c["file"], "name": c["name"], "kind": c["kind"],
                "line": c["line"], "sig": c["sig"], "score": round(score, 3),
            })
        return results
