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

    `probe_chars` 是**目标块长**，`max_tokens` 是**上限**——两者不是一回事。
    曾经写过"在不超限的前提下尽量把块填满"，结果真实语料上块数从 1322 掉到 770，
    簇从 5 个（含 3 个极干净的）退化成 2 个大杂烩：块越大，主题信号被摊得越平。
    分块器的职责是保证不超限，不是尽量填满。
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
            if self._count(text[pos:hi]) > self._max_tokens:
                lo, high = pos + 1, hi
                while lo < high:                    # 二分找不超限的最大 end
                    mid = (lo + high + 1) // 2
                    if self._count(text[pos:mid]) <= self._max_tokens:
                        lo = mid
                    else:
                        high = mid - 1
                hi = lo
                if self._count(text[pos:hi]) > self._max_tokens:
                    # 连一个字符都放不下。切不动就必须报出来——默默放行等于
                    # 又一次静默截断，而躲开静默截断正是这个类存在的理由。
                    raise ValueError(
                        f"单个字符的 token 数已超过上限 {self._max_tokens}（位置 {pos}）"
                    )
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

        # **必须关掉 truncation**：tokenizer 默认截断到 512，于是 len(ids) 恒 ≤ 512，
        # 计数函数永远报告"没超限"，分块器把整篇文档当成一块——正是这条硬约束要防的
        # 静默截断，而且断言「每块 ≤512 token」在截断下恒真，测试也发现不了。
        # 实测证据：287 篇语料，关之前切出 287 块，关之后切出 1300+ 块。
        # 这里的 model 是 build_splitter 自己新建的实例，与推理用的实例无关，改它安全。
        if hasattr(tokenizer, "no_truncation"):
            tokenizer.no_truncation()

        def count(text: str) -> int:
            return len(tokenizer.encode(text).ids)

        # 关完还要**验一次**：`no_truncation()` 不存在或没生效时，计数会恒 ≤ 上限，
        # token-safe 就成了一句空话，而所有断言都会恒真、测不出来。
        # 探针取一段远超上限的文本；若它的计数没超限，说明还在截断。
        if count("x " * (MAX_TOKENS * 3)) <= MAX_TOKENS:
            raise RuntimeError("tokenizer 的 truncation 关不掉，计数不可信")

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


def model_revision(model_name: str = DEFAULT_MODEL) -> str:
    """模型版本标识，写进 `method.model_revision` 供可复现性比对。

    形如 `BAAI/bge-small-zh-v1.5@onnx/model.onnx`。取自 fastembed 的模型目录
    而不是实例属性——实例上并没有 `model_description`，此前那版 getattr 兜底
    会静默返回空串，等于这个字段一直是摆设。取不到时退回模型名：这是元数据，
    不值得为它让整个索引失败，但也不能假装它有值。
    """
    try:
        from fastembed import TextEmbedding

        for entry in TextEmbedding.list_supported_models():
            if entry.get("model") == model_name:
                sources = entry.get("sources") or {}
                repo = sources.get("hf") or model_name
                return f"{repo}@{entry.get('model_file', '')}"
    except Exception:
        pass
    return model_name


def _fastembed_version() -> str:
    try:
        from importlib.metadata import version

        return f"fastembed-{version('fastembed')}"
    except Exception:
        return "fastembed-unknown"


class FastEmbedEmbedder:
    """真实推理适配器。fastembed 在**方法内部**导入，模块顶层保持干净。"""

    def __init__(self, model_name: str = DEFAULT_MODEL, progress=None) -> None:
        self.model_name = model_name
        self._progress = progress
        self._model = None
        self.revision = ""

    @property
    def provenance(self) -> str:
        """自报家门，供 `index.json` 的 `versions.embedder_adapter` 使用。

        由适配器自己提供，而不是让 pipeline 猜：注入假实现时如果仍写 fastembed，
        产物就在撒谎；反过来，管线自建的真适配器被记成 injected 也一样是错的。
        """
        return _fastembed_version()

    def _ensure(self):
        if self._model is None:
            from fastembed import TextEmbedding

            if self._progress:
                self._progress({"event": "model_loading", "model": self.model_name})
            self._model = TextEmbedding(model_name=self.model_name)
            self.revision = model_revision(self.model_name)
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
