"""块 → 向量 → 文档向量。

fastembed **只在适配器内部惰性导入**：`--no-index` 路径与全部单元测试都不该
为了一个不会用到的 ONNX 运行时付出导入代价，更不该因为平台缺 wheel 就崩在 import 上。
"""
from __future__ import annotations

from typing import Iterable, Protocol, Sequence

import numpy as np

from kb_init.chunk import Chunk


class EmbeddingError(RuntimeError):
    """embedding 产出不合法。语义是 fail closed——绝不把坏向量写进产物。"""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> Iterable[np.ndarray]: ...


def pool_chunk_vectors(
    chunks: Sequence[Chunk], vectors: Sequence[np.ndarray]
) -> tuple[list[str], np.ndarray]:
    """块向量 → 文档向量：按 doc 均值池化后 L2 归一化。

    行序按 doc_id 升序，**与聚类结果无关**——拿聚类顺序当行序会让产物依赖算法参数。
    """
    if len(vectors) != len(chunks):
        raise EmbeddingError(f"向量数 {len(vectors)} 与块数 {len(chunks)} 不符")
    if not chunks:
        return [], np.zeros((0, 0), dtype=np.float32)

    dim = int(np.asarray(vectors[0]).shape[-1])
    doc_ids = sorted({c.doc_id for c in chunks})
    row_of = {doc_id: i for i, doc_id in enumerate(doc_ids)}

    pooled = np.zeros((len(doc_ids), dim), dtype=np.float32)
    counts = np.zeros(len(doc_ids), dtype=np.float32)
    for chunk, vec in zip(chunks, vectors):
        arr = np.asarray(vec, dtype=np.float32)
        if arr.ndim != 1 or arr.shape[0] != dim:
            raise EmbeddingError(f"向量形状不一致：期望 ({dim},)，得到 {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise EmbeddingError("向量含 NaN 或 Inf")
        if not float(np.linalg.norm(arr)):
            raise EmbeddingError("向量范数为零，无法归一化")
        row = row_of[chunk.doc_id]
        pooled[row] += arr
        counts[row] += 1

    pooled /= counts[:, None]
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    if not np.all(norms > 0):
        raise EmbeddingError("池化后出现零向量")
    return doc_ids, (pooled / norms).astype(np.float32)


DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
MAX_TOKENS = 512


class TokenSafeSplitter:
    """按**真实 token 数**切分，而不是按字符数猜。

    DESIGN §7 把「不分块 → 长笔记静默截断」列为硬约束。400 字符只是中文近似
    1 字 1 token 的启发式：英文、代码、长符号串都可能在 400 字符内突破 512 token，
    而那正是这条硬约束要防的事。用启发式挡它等于没挡。

    做法是从 `probe_chars` 起步、必要时二分收缩到不超限的最大片段——比逐字符
    累加 token 少调用几个数量级的 tokenizer。
    """

    def __init__(
        self, count_tokens, max_tokens: int = MAX_TOKENS, probe_chars: int = 400
    ) -> None:
        self._count = count_tokens
        self._max_tokens = max_tokens
        self._probe = probe_chars

    def split(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        pos = 0
        n = len(text)
        while pos < n:
            hi = min(pos + self._probe, n)
            if self._count(text[pos:hi]) <= self._max_tokens:
                # 还有余量且未到结尾时向后扩，避免把长文切得过碎
                while hi < n:
                    nxt = min(hi + self._probe, n)
                    if self._count(text[pos:nxt]) > self._max_tokens:
                        break
                    hi = nxt
            else:
                lo, high = pos + 1, hi
                while lo < high:                    # 二分找不超限的最大 end
                    mid = (lo + high + 1) // 2
                    if self._count(text[pos:mid]) <= self._max_tokens:
                        lo = mid
                    else:
                        high = mid - 1
                hi = lo
            spans.append((pos, hi))
            pos = hi
        return spans


def build_splitter(model_name: str = DEFAULT_MODEL):
    """返回 (splitter, splitter_meta)。拿不到真 tokenizer 就降级并**如实记录**。"""
    try:
        from fastembed import TextEmbedding             # 惰性导入

        model = TextEmbedding(model_name=model_name)
        tokenizer = getattr(getattr(model, "model", None), "tokenizer", None)
        if tokenizer is None:
            raise AttributeError("该 fastembed 版本未暴露 tokenizer")

        def count(text: str) -> int:
            return len(tokenizer.encode(text).ids)

        return (
            TokenSafeSplitter(count, MAX_TOKENS),
            {"name": "token_safe", "max_tokens": MAX_TOKENS, "fallback_used": False},
        )
    except Exception:
        # 降级不是失败，但必须让产物说实话：method.splitter.fallback_used=True
        from kb_init.chunk import CharSplitter

        return (
            CharSplitter(max_chars=400),
            {"name": "char", "max_tokens": MAX_TOKENS, "fallback_used": True},
        )


def _model_revision(model) -> str:
    """取模型版本标识写进 method.model_revision，供可复现性比对。

    fastembed 各版本的 `model_description` 有时是 dataclass、有时是 dict，
    取不到就返回空串——这是元数据，不该为了它让整个索引失败。
    """
    description = getattr(model, "model_description", None)
    if description is None:
        return ""
    if isinstance(description, dict):
        return str(description.get("model_file", ""))
    return str(getattr(description, "model_file", ""))


class FastEmbedEmbedder:
    """真实推理适配器。fastembed 在**方法内部**导入，模块顶层保持干净。"""

    def __init__(self, model_name: str = DEFAULT_MODEL, progress=None) -> None:
        self.model_name = model_name
        self._progress = progress
        self._model = None
        self.revision = ""

    def _ensure(self):
        if self._model is None:
            from fastembed import TextEmbedding

            if self._progress:
                self._progress({"event": "model_loading", "model": self.model_name})
            self._model = TextEmbedding(model_name=self.model_name)
            self.revision = _model_revision(self._model)
        return self._model

    def embed(self, texts: list[str]):
        model = self._ensure()
        done = 0
        for vec in model.embed(texts):
            done += 1
            if self._progress and done % 200 == 0:
                self._progress(
                    {"event": "embedding", "done": done, "total": len(texts)}
                )
            yield vec
