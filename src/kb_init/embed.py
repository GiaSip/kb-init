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
