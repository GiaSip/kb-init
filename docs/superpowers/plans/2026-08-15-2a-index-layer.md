# 2A 索引层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Plan 1 的清洗产物之上加一步索引——分块 → 本地 embedding → 聚类 → 产出 `index.json` + 向量产物，供后续 2B 洞察层消费。

**Architecture:** 四个新模块单向依赖（`chunk` → `embed` → `cluster` → `index`），`index.py` 是唯一写盘者。索引在 pipeline 的 staging 内以窄边界运行，失败被吸收成状态而非异常，保证清洗产物照常发布。所有跨模块接口用 Protocol 注入，单元测试永不下载模型。

**Tech Stack:** Python 3.12 / numpy / scikit-learn（HDBSCAN）/ fastembed（ONNX CPU 推理）/ pytest

**Spec:** `docs/superpowers/specs/2026-08-15-2a-index-layer-design.md`

## Global Constraints

- **单元测试绝不下载模型、绝不联网。** fastembed 只能在适配器内部**惰性导入**，模块顶层禁止 `import fastembed`。
- **`index.py` 是本层唯一写盘的模块**（对应 `emit.py` 在 Plan 1 的地位）。`chunk.py` / `embed.py` / `cluster.py` 均为纯函数，不碰文件系统。
- **偏移单位 = Python `str` 索引（Unicode code point）**，不是字节。`text[start:end]` 必须能逐字重建原块。
- **向量矩阵行序 = doc_id 升序**，与聚类结果无关。
- **`except Exception` 而非 `except BaseException`**：`KeyboardInterrupt` / `SystemExit` 必须透传，不得被伪装成 partial success。
- **退出码合同**：0 成功 / 1 输出冲突 / 2 用法错误 / 3 输入不安全或损坏 / 4 I-O 失败 / **5 产物已发布但索引未完成**。
- **依赖版本下限**：`numpy>=1.24`、`scikit-learn>=1.3`（HDBSCAN 在 1.3 才进 sklearn.cluster）、`fastembed>=0.3`。
- **默认模型**：`BAAI/bge-small-zh-v1.5`，512 维，token 上限 512。
- **默认聚类参数**：`min_cluster_size=5`、`min_samples=5`、`metric="euclidean"`、`seed=0`。
- 注释写「为什么」不写「做了什么」，与既有代码风格一致；中文注释。

---

### Task 1: 分块（`chunk.py`）

**Files:**
- Create: `src/kb_init/chunk.py`
- Test: `tests/test_chunk.py`
- Modify: `pyproject.toml`（本任务不加依赖，chunk 层零依赖——此处不改，列出以示确认）

**Interfaces:**
- Produces:
  - `Chunk`（frozen dataclass）：`chunk_id: str`、`doc_id: str`、`start: int`、`end: int`
  - `class Splitter(Protocol): def split(self, text: str) -> list[tuple[int, int]]`
  - `CharSplitter(max_chars: int = 400)` — 实现 `Splitter`
  - `chunk_documents(docs: Sequence[tuple[str, str]], splitter: Splitter) -> list[Chunk]`
  - `docs` 形如 `[(doc_id, text)]`；**空文档产出 0 个块**，由调用方负责给它 residual

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chunk.py
from kb_init.chunk import CharSplitter, chunk_documents


def test_chunks_can_reconstruct_original_text():
    """偏移必须能逐字重建原块——这是 chunks 只存偏移不存正文的前提。"""
    text = "中文内容" * 300           # 1200 字符，跨多块
    chunks = chunk_documents([("d1", text)], CharSplitter(max_chars=400))
    assert len(chunks) == 3
    rebuilt = "".join(text[c.start:c.end] for c in chunks)
    assert rebuilt == text


def test_chunk_ids_are_unique_and_map_back_to_doc():
    docs = [("d1", "a" * 500), ("d2", "b" * 100)]
    chunks = chunk_documents(docs, CharSplitter(max_chars=400))
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert [c.doc_id for c in chunks] == ["d1", "d1", "d2"]


def test_empty_document_produces_no_chunks():
    """空文档不产块。调用方据此给它 residual，而不是让它变成零向量。"""
    assert chunk_documents([("d1", "")], CharSplitter()) == []


def test_exact_multiple_does_not_produce_trailing_empty_chunk():
    chunks = chunk_documents([("d1", "x" * 800)], CharSplitter(max_chars=400))
    assert len(chunks) == 2
    assert chunks[-1].end == 800
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_chunk.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.chunk'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/chunk.py
"""文档 → 块。只产生映射，不写盘（写盘统一在 index.py）。

偏移单位是 Python `str` 索引（Unicode code point）而非字节：语料是中英意混排，
用字节偏移会在重建时错位。`text[start:end]` 必须逐字等于原块。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    start: int
    end: int


class Splitter(Protocol):
    """把正文切成不超过模型 token 上限的片段，返回 (start, end) 偏移对。"""

    def split(self, text: str) -> list[tuple[int, int]]: ...


@dataclass(frozen=True)
class CharSplitter:
    """按字符数切分。

    这是**降级实现**：中文近似 1 字 1 token，但英文/代码/长符号串可能在 400 字符内
    突破 512 token。真实分块走 embed.py 的 TokenSafeSplitter，此实现用于无 tokenizer
    可用时的兜底与测试。
    """

    max_chars: int = 400

    def split(self, text: str) -> list[tuple[int, int]]:
        if not text:
            return []
        return [
            (i, min(i + self.max_chars, len(text)))
            for i in range(0, len(text), self.max_chars)
        ]


def chunk_documents(
    docs: Sequence[tuple[str, str]], splitter: Splitter
) -> list[Chunk]:
    """`docs` 形如 [(doc_id, 正文)]。空文档产出 0 个块。"""
    chunks: list[Chunk] = []
    seq = 0
    for doc_id, text in docs:
        for start, end in splitter.split(text):
            seq += 1
            chunks.append(Chunk(f"c{seq:05d}", doc_id, start, end))
    return chunks
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_chunk.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/chunk.py tests/test_chunk.py
git commit -m "feat(chunk): 文档分块，偏移可逐字重建原文

偏移单位钉死为 Unicode code point 而非字节——语料是中英意混排，
字节偏移会在重建时错位。CharSplitter 明确标注为降级实现：
400 字符只是中文近似，英文/代码会突破 512 token 上限。"
```

---

### Task 2: 池化与产出校验（`embed.py` 纯函数部分）

**Files:**
- Create: `src/kb_init/embed.py`
- Create: `tests/fakes.py`
- Test: `tests/test_embed.py`
- Modify: `pyproject.toml`（加 `numpy>=1.24`）

**Interfaces:**
- Consumes: `kb_init.chunk.Chunk`
- Produces:
  - `class Embedder(Protocol): def embed(self, texts: list[str]) -> Iterable[np.ndarray]`
  - `class EmbeddingError(RuntimeError)`
  - `pool_chunk_vectors(chunks: Sequence[Chunk], vectors: Sequence[np.ndarray]) -> tuple[list[str], np.ndarray]`
    返回 `(doc_ids 升序, 矩阵)`，行序与 doc_ids 一致，已 L2 归一化，dtype `float32`
  - `tests/fakes.py` 的 `FakeEmbedder(dim=8)`（SHA-256 派生的确定性向量）与 `BrokenEmbedder(mode=...)`

- [ ] **Step 1: 写失败测试**

```python
# tests/fakes.py
"""测试用的确定性假 embedder。

向量由 SHA-256 派生而非 Python 内置 hash()——后者带进程级随机盐，
会让测试在不同进程间随机飘。
"""
from __future__ import annotations

import hashlib

import numpy as np


def fake_vector(text: str, dim: int = 8) -> np.ndarray:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = np.frombuffer((digest * ((dim // len(digest)) + 1))[:dim], dtype=np.uint8)
    return (raw.astype(np.float32) / 255.0)


class FakeEmbedder:
    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        for t in texts:
            yield fake_vector(t, self.dim)


class BrokenEmbedder:
    """按 mode 制造各种非法产出，用于验证 fail closed。"""

    def __init__(self, mode: str, dim: int = 8) -> None:
        self.mode = mode
        self.dim = dim

    def embed(self, texts: list[str]):
        for i, t in enumerate(texts):
            if self.mode == "short" and i == len(texts) - 1:
                return                                  # 少一个向量
            if self.mode == "dim_shift" and i == 1:
                yield np.ones(self.dim + 3, dtype=np.float32)
                continue
            if self.mode == "nan" and i == 0:
                yield np.full(self.dim, np.nan, dtype=np.float32)
                continue
            if self.mode == "inf" and i == 0:
                yield np.full(self.dim, np.inf, dtype=np.float32)
                continue
            if self.mode == "zero" and i == 0:
                yield np.zeros(self.dim, dtype=np.float32)
                continue
            if self.mode == "raise" and i == 1:
                raise RuntimeError("推理中途炸了")
            yield fake_vector(t, self.dim)
```

```python
# tests/test_embed.py
import numpy as np
import pytest

from kb_init.chunk import Chunk
from kb_init.embed import EmbeddingError, pool_chunk_vectors
from tests.fakes import BrokenEmbedder, FakeEmbedder, fake_vector


def _chunks():
    return [
        Chunk("c1", "d2", 0, 4),
        Chunk("c2", "d2", 4, 8),
        Chunk("c3", "d1", 0, 4),
    ]


def test_pooling_averages_chunks_then_l2_normalizes():
    chunks = _chunks()
    vectors = [np.array([1.0, 0.0], np.float32),
               np.array([0.0, 1.0], np.float32),
               np.array([3.0, 4.0], np.float32)]
    doc_ids, matrix = pool_chunk_vectors(chunks, vectors)

    # 行序按 doc_id 升序，与块的出现顺序无关
    assert doc_ids == ["d1", "d2"]
    # d1 只有一块 (3,4)，归一化后是 (0.6, 0.8)
    assert np.allclose(matrix[0], [0.6, 0.8])
    # d2 两块均值 (0.5,0.5)，归一化后是 (√2/2, √2/2)
    assert np.allclose(matrix[1], [2 ** -0.5, 2 ** -0.5])
    assert matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)


@pytest.mark.parametrize("mode", ["short", "dim_shift", "nan", "inf", "zero"])
def test_illegal_embedder_output_fails_closed(mode):
    """坏向量绝不能被写进产物——宁可整个索引失败。"""
    chunks = _chunks()
    texts = ["a", "b", "c"]
    broken = BrokenEmbedder(mode=mode, dim=2)
    with pytest.raises(EmbeddingError):
        pool_chunk_vectors(chunks, list(broken.embed(texts)))


def test_embedder_raising_midway_is_not_swallowed():
    chunks = _chunks()
    with pytest.raises(RuntimeError):
        list(BrokenEmbedder(mode="raise", dim=2).embed(["a", "b", "c"]))


def test_fake_embedder_is_deterministic_across_calls():
    assert np.array_equal(fake_vector("同一段文本"), fake_vector("同一段文本"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_embed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.embed'`

- [ ] **Step 3: 加依赖并写实现**

```toml
# pyproject.toml —— dependencies 一行改成：
dependencies = ["PyYAML>=6.0", "numpy>=1.24"]
```

```python
# src/kb_init/embed.py
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
        raise EmbeddingError(
            f"向量数 {len(vectors)} 与块数 {len(chunks)} 不符"
        )
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_embed.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/embed.py tests/test_embed.py tests/fakes.py pyproject.toml
git commit -m "feat(embed): 均值池化 + L2 归一，非法产出一律 fail closed

对抗式假 embedder 覆盖六种坏产出（少向量/维度漂移/NaN/Inf/零范数/中途抛错），
每一种都必须炸在这里而不是把坏向量写进产物。fake 向量用 SHA-256 派生，
不用内置 hash()——后者带进程级随机盐会让测试随机飘。"
```

---

### Task 3: 聚类与拒答（`cluster.py`）

**Files:**
- Create: `src/kb_init/cluster.py`
- Test: `tests/test_cluster.py`
- Modify: `pyproject.toml`（加 `scikit-learn>=1.3`）

**Interfaces:**
- Consumes: 无（只吃 `list[str]` + `np.ndarray`）
- Produces:
  - `Membership(group_id: str, role: str, score: float)`
  - `Assignment(doc_id: str, disposition: str, memberships: tuple[Membership, ...], reason_code: str | None)`
  - `Group(group_id: str, kind: str, member_counts: dict[str, int], representatives: list[dict], prototype: dict)`
  - `cluster_documents(doc_ids: Sequence[str], matrix: np.ndarray, *, min_cluster_size: int = 5, min_samples: int = 5) -> tuple[list[Group], list[Assignment]]`
  - `MIN_DOCS_FACTOR = 2`（语料下限 = `min_cluster_size * 2`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cluster.py
import numpy as np
import pytest

from kb_init.cluster import cluster_documents


def _two_blobs(n=12, dim=8, seed=0):
    """两团明显分开的点，doc_id 故意乱序给进去。"""
    rng = np.random.default_rng(seed)
    a = np.tile(np.eye(dim, dtype=np.float32)[0], (n, 1)) + rng.normal(0, 0.01, (n, dim))
    b = np.tile(np.eye(dim, dtype=np.float32)[1], (n, 1)) + rng.normal(0, 0.01, (n, dim))
    m = np.vstack([a, b]).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    ids = [f"d{i:02d}" for i in range(2 * n)]
    return ids, m


def test_finds_two_groups_and_every_doc_has_exactly_one_assignment():
    ids, m = _two_blobs()
    groups, assignments = cluster_documents(ids, m, min_cluster_size=5, min_samples=3)
    assert len(groups) == 2
    assert sorted(a.doc_id for a in assignments) == sorted(ids)   # 恰有一条


def test_result_is_invariant_under_input_permutation():
    """打乱输入顺序结果必须不变——否则 index.json 不可复现。"""
    ids, m = _two_blobs()
    g1, a1 = cluster_documents(ids, m, min_cluster_size=5, min_samples=3)

    order = np.random.default_rng(7).permutation(len(ids))
    shuffled_ids = [ids[i] for i in order]
    g2, a2 = cluster_documents(shuffled_ids, m[order], min_cluster_size=5, min_samples=3)

    assert [g.group_id for g in g1] == [g.group_id for g in g2]
    assert [(g.group_id, g.member_counts) for g in g1] == [
        (g.group_id, g.member_counts) for g in g2
    ]
    key = lambda a: a.doc_id
    assert [(a.doc_id, a.disposition, [m.group_id for m in a.memberships])
            for a in sorted(a1, key=key)] == \
           [(a.doc_id, a.disposition, [m.group_id for m in a.memberships])
            for a in sorted(a2, key=key)]


def test_corpus_too_small_is_not_an_error():
    ids = ["d1", "d2", "d3"]
    m = np.eye(3, 8, dtype=np.float32)
    groups, assignments = cluster_documents(ids, m, min_cluster_size=5, min_samples=5)
    assert groups == []
    assert {a.disposition for a in assignments} == {"residual"}
    assert {a.reason_code for a in assignments} == {"corpus_too_small"}


def test_residual_docs_carry_empty_memberships_and_reason():
    ids, m = _two_blobs(n=8)
    # 掺一个远离两团的离群点
    ids = ids + ["zz_outlier"]
    outlier = np.zeros((1, m.shape[1]), dtype=np.float32)
    outlier[0, 5] = 1.0
    m = np.vstack([m, outlier]).astype(np.float32)

    _, assignments = cluster_documents(ids, m, min_cluster_size=5, min_samples=3)
    outlier_assignment = next(a for a in assignments if a.doc_id == "zz_outlier")
    assert outlier_assignment.disposition == "residual"
    assert outlier_assignment.memberships == ()
    assert outlier_assignment.reason_code == "low_local_density"


def test_groups_carry_medoid_representative_and_role_counts():
    ids, m = _two_blobs()
    groups, _ = cluster_documents(ids, m, min_cluster_size=5, min_samples=3)
    for g in groups:
        assert g.representatives and g.representatives[0]["kind"] == "medoid"
        assert g.representatives[0]["doc_id"] in ids
        assert g.member_counts["core"] == g.member_counts["total_docs"]
        assert g.member_counts["halo"] == 0 and g.member_counts["micro"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cluster.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.cluster'`

- [ ] **Step 3: 加依赖并写实现**

```toml
# pyproject.toml —— dependencies 一行改成：
dependencies = ["PyYAML>=6.0", "numpy>=1.24", "scikit-learn>=1.3"]
```

```python
# src/kb_init/cluster.py
"""文档向量 → 归属。只吃向量与 doc_id，**不认识文本**——换聚类算法不碰解析层。

「拒绝归属」是一等结果而不是失败：强行把每篇都塞进最近的簇，会把语料里本来零散的
部分摊进去，稀释成人看不出是什么的大杂烩。宁可说「这些没有主题」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from sklearn.cluster import HDBSCAN

MIN_DOCS_FACTOR = 2


@dataclass(frozen=True)
class Membership:
    group_id: str
    role: str
    score: float


@dataclass(frozen=True)
class Assignment:
    doc_id: str
    disposition: str
    memberships: tuple[Membership, ...] = ()
    reason_code: str | None = None


@dataclass(frozen=True)
class Group:
    group_id: str
    kind: str
    member_counts: dict[str, int]
    representatives: list[dict]
    prototype: dict = field(
        default_factory=lambda: {
            "kind": "mean_of_members",
            "member_role": "core",
            "metric": "cosine",
        }
    )


def _all_residual(doc_ids: Sequence[str], reason: str) -> list[Assignment]:
    return [Assignment(d, "residual", (), reason) for d in sorted(doc_ids)]


def _medoid(members: list[str], rows: dict[str, np.ndarray]) -> str:
    """与同簇其余成员平均余弦相似度最高的那一篇。

    向量已 L2 归一化，故点积即余弦。代表物不是内部细节——DESIGN §5 要求 L3 用
    「kNN / 簇代表」生成候选而绝不遍历所有文档对。
    """
    mat = np.vstack([rows[d] for d in members])
    sims = mat @ mat.T
    return members[int(np.argmax(sims.sum(axis=1)))]


def cluster_documents(
    doc_ids: Sequence[str],
    matrix: np.ndarray,
    *,
    min_cluster_size: int = 5,
    min_samples: int = 5,
) -> tuple[list[Group], list[Assignment]]:
    doc_ids = list(doc_ids)
    if len(doc_ids) != matrix.shape[0]:
        raise ValueError(f"doc_id 数 {len(doc_ids)} 与矩阵行数 {matrix.shape[0]} 不符")
    if len(doc_ids) < min_cluster_size * MIN_DOCS_FACTOR:
        return [], _all_residual(doc_ids, "corpus_too_small")

    # 先按 doc_id 排序再聚类：HDBSCAN 对输入顺序不是完全不敏感，排序把
    # 「打乱输入结果不变」变成结构性保证，而不是碰运气。
    order = np.argsort(np.array(doc_ids, dtype=object), kind="stable")
    sorted_ids = [doc_ids[i] for i in order]
    sorted_matrix = np.ascontiguousarray(matrix[order])

    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
    )
    labels = model.fit_predict(sorted_matrix)
    probabilities = getattr(model, "probabilities_", np.ones(len(sorted_ids)))

    rows = {d: sorted_matrix[i] for i, d in enumerate(sorted_ids)}
    members_of: dict[int, list[str]] = {}
    for doc_id, label in zip(sorted_ids, labels):
        if label != -1:
            members_of.setdefault(int(label), []).append(doc_id)

    # 按「成员集合」重编号，而不是沿用 HDBSCAN 的原始 label：原始 label 的编号
    # 依赖内部遍历顺序，换一次 sklearn 版本就可能整体重排，index.json 便不可复现。
    ordered = sorted(members_of.values(), key=lambda ms: (len(ms) * -1, ms))
    group_of_doc: dict[str, str] = {}
    groups: list[Group] = []
    for i, members in enumerate(ordered, start=1):
        group_id = f"g{i:02d}"
        for d in members:
            group_of_doc[d] = group_id
        groups.append(
            Group(
                group_id=group_id,
                kind="semantic_topic",
                member_counts={
                    "core": len(members),
                    "halo": 0,
                    "micro": 0,
                    "total_docs": len(members),
                },
                representatives=[{"doc_id": _medoid(members, rows), "kind": "medoid"}],
            )
        )

    score_of = dict(zip(sorted_ids, (float(p) for p in probabilities)))
    assignments = []
    for doc_id in sorted_ids:
        group_id = group_of_doc.get(doc_id)
        if group_id is None:
            assignments.append(Assignment(doc_id, "residual", (), "low_local_density"))
        else:
            assignments.append(
                Assignment(
                    doc_id,
                    "assigned",
                    (Membership(group_id, "core", round(score_of[doc_id], 6)),),
                    None,
                )
            )
    return groups, assignments
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_cluster.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/cluster.py tests/test_cluster.py pyproject.toml
git commit -m "feat(cluster): HDBSCAN 拒答式聚类，簇号按成员集合确定性重编号

两处刻意设计：① 聚类前先按 doc_id 排序，把「打乱输入结果不变」变成结构性保证
而不是碰运气；② 不沿用 HDBSCAN 原始 label，改按成员集合重编号——原始编号依赖
内部遍历顺序，换个 sklearn 版本就可能整体重排，index.json 便不可复现。

medoid 现在就产出：DESIGN §5 要求 L3 用「kNN/簇代表」生成候选而绝不遍历
所有文档对，代表物是上游合同的一部分，不是内部细节。"
```

---

### Task 4: 索引组装与原子落盘（`index.py`）

**Files:**
- Create: `src/kb_init/index.py`
- Test: `tests/test_index.py`

**Interfaces:**
- Consumes: `Chunk`、`Group`、`Assignment`、`Membership`
- Produces:
  - `SCHEMA_VERSION = "0.1"`、`TIME_AXIS_THRESHOLD = 0.30`
  - `build_time_axis(dated_docs: int, total_docs: int, threshold: float = TIME_AXIS_THRESHOLD) -> dict`
  - `build_index(*, run_id, corpus_hash, chunks, groups, assignments, method, time_axis, versions) -> dict`
  - `write_index(out_dir: Path, index: dict, matrix: np.ndarray) -> None`（子事务：两个文件要么都在，要么都不在）
  - `validate_index(index: dict, kept_doc_ids: Sequence[str]) -> None`（合同自检，违约抛 `ValueError`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_index.py
import json

import numpy as np
import pytest

from kb_init.chunk import Chunk
from kb_init.cluster import Assignment, Group, Membership
from kb_init.index import (
    build_index,
    build_time_axis,
    validate_index,
    write_index,
)


def _fixture():
    chunks = [Chunk("c00001", "d1", 0, 4), Chunk("c00002", "d2", 0, 4)]
    groups = [Group("g01", "semantic_topic",
                    {"core": 1, "halo": 0, "micro": 0, "total_docs": 1},
                    [{"doc_id": "d1", "kind": "medoid"}])]
    assignments = [
        Assignment("d1", "assigned", (Membership("g01", "core", 0.9),), None),
        Assignment("d2", "residual", (), "low_local_density"),
    ]
    index = build_index(
        run_id="r1", corpus_hash="h1", chunks=chunks, groups=groups,
        assignments=assignments,
        method={"family": "density", "name": "hdbscan", "model": "m",
                "model_revision": "rev", "params": {"min_cluster_size": 5},
                "seed": 0, "splitter": {"name": "char", "max_tokens": 512,
                                        "fallback_used": True},
                "pooling": "mean_l2", "score_kind": "density_membership",
                "score_direction": "higher_better", "decision_threshold": None},
        time_axis=build_time_axis(1, 2),
        versions={"kb_init": "0.2.0"},
    )
    return index, np.eye(2, 4, dtype=np.float32)


def test_time_axis_below_threshold_is_unavailable_and_has_no_per_group():
    ta = build_time_axis(39, 757)
    assert ta["coverage"] == pytest.approx(0.0515, abs=1e-3)
    assert ta["available"] is False
    assert ta["per_group"] is None


def test_time_axis_handles_empty_corpus_without_dividing_by_zero():
    ta = build_time_axis(0, 0)
    assert ta["coverage"] == 0.0
    assert ta["available"] is False


def test_index_is_wrapped_in_analyses_array_from_day_one():
    index, _ = _fixture()
    assert isinstance(index["analyses"], list) and len(index["analyses"]) == 1
    analysis = index["analyses"][0]
    assert analysis["analysis_id"] == "topics-01"
    assert analysis["parent_analysis_id"] is None
    assert analysis["input_scope"] == {"kind": "all_kept_docs"}


def test_coverage_is_derived_from_assignments():
    index, _ = _fixture()
    assert index["analyses"][0]["coverage"] == {
        "assigned": 1, "ambiguous": 0, "residual": 1
    }


def test_validate_rejects_doc_without_assignment():
    index, _ = _fixture()
    with pytest.raises(ValueError, match="恰有一条"):
        validate_index(index, ["d1", "d2", "d3"])


def test_validate_rejects_membership_pointing_at_unknown_group():
    index, _ = _fixture()
    index["analyses"][0]["assignments"][0]["memberships"][0]["group_id"] = "g99"
    with pytest.raises(ValueError, match="不存在的 group"):
        validate_index(index, ["d1", "d2"])


def test_write_index_publishes_both_files(tmp_path):
    index, matrix = _fixture()
    write_index(tmp_path, index, matrix)
    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "index-vectors.npy").exists()
    loaded = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "0.1"


def test_write_index_leaves_nothing_behind_when_vector_write_fails(tmp_path, monkeypatch):
    """索引是子事务：两个文件要么都在，要么都不在。"""
    index, matrix = _fixture()

    def boom(*a, **k):
        raise OSError("磁盘满了")

    monkeypatch.setattr("kb_init.index.np.save", boom)
    with pytest.raises(OSError):
        write_index(tmp_path, index, matrix)
    assert list(tmp_path.iterdir()) == []


def test_write_index_leaves_nothing_behind_when_json_write_fails(tmp_path, monkeypatch):
    index, matrix = _fixture()
    real_write = __import__("pathlib").Path.write_text

    def boom(self, *a, **k):
        if self.name.endswith(".json"):
            raise OSError("磁盘满了")
        return real_write(self, *a, **k)

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(OSError):
        write_index(tmp_path, index, matrix)
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_index.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.index'`

- [ ] **Step 3: 写实现**

```python
# src/kb_init/index.py
"""组装 index.json 并落盘。本层**唯一**写盘的模块。

`analyses` 从第一天就是数组：将来 residual 二次微聚类需要同时保留「第一轮 residual」
与「第二轮 micro assigned」两套 disposition，单顶层结构表达不了，等到那时再改
就是破坏性迁移。现在多写一层数组是零成本。
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Sequence

import json
import numpy as np

from kb_init.chunk import Chunk
from kb_init.cluster import Assignment, Group

SCHEMA_VERSION = "0.1"
TIME_AXIS_THRESHOLD = 0.30
ANALYSIS_ID = "topics-01"

_INDEX_FILES = ("index.json", "index-vectors.npy")


def build_time_axis(
    dated_docs: int, total_docs: int, threshold: float = TIME_AXIS_THRESHOLD
) -> dict:
    """只报事实，不做判断：是否变成一条洞察由 2B 决定。

    阈值取在实测的两档语料之间（导出类 5–6%，已维护类 43%），中间是空的，
    0.10–0.40 的任何取值在现有证据下行为相同。
    """
    coverage = (dated_docs / total_docs) if total_docs else 0.0
    available = coverage >= threshold
    return {
        "dated_docs": dated_docs,
        "total_docs": total_docs,
        "coverage": round(coverage, 6),
        "threshold": threshold,
        "available": available,
        "per_group": None,          # 仅当 available 为真时才由 2B 填充
    }


def build_index(
    *,
    run_id: str,
    corpus_hash: str,
    chunks: Sequence[Chunk],
    groups: Sequence[Group],
    assignments: Sequence[Assignment],
    method: dict,
    time_axis: dict,
    versions: dict,
) -> dict:
    dispositions = [a.disposition for a in assignments]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "corpus_hash": corpus_hash,
        "versions": versions,
        "chunks": [asdict(c) for c in chunks],
        "analyses": [
            {
                "analysis_id": ANALYSIS_ID,
                "parent_analysis_id": None,
                "input_scope": {"kind": "all_kept_docs"},
                "method": method,
                "groups": [
                    {
                        "group_id": g.group_id,
                        "kind": g.kind,
                        "member_counts": g.member_counts,
                        "representatives": g.representatives,
                        "prototype": g.prototype,
                    }
                    for g in groups
                ],
                "assignments": [
                    {
                        "doc_id": a.doc_id,
                        "disposition": a.disposition,
                        "memberships": [asdict(m) for m in a.memberships],
                        "reason_code": a.reason_code,
                    }
                    for a in assignments
                ],
                # coverage 必须由 assignments 派生。独立计数迟早会与 assignments
                # 漂移，而漂移后没有任何测试会发现。
                "coverage": {
                    "assigned": dispositions.count("assigned"),
                    "ambiguous": dispositions.count("ambiguous"),
                    "residual": dispositions.count("residual"),
                },
                "time_axis": time_axis,
            }
        ],
    }


def validate_index(index: dict, kept_doc_ids: Sequence[str]) -> None:
    """合同自检。宁可在写盘前炸，也不要产出一份下游读不懂的索引。"""
    analysis = index["analyses"][0]
    assigned_ids = [a["doc_id"] for a in analysis["assignments"]]
    if sorted(assigned_ids) != sorted(kept_doc_ids):
        raise ValueError("每个 kept 文档必须恰有一条 assignment")
    if len(set(assigned_ids)) != len(assigned_ids):
        raise ValueError("assignment 出现重复 doc_id")

    known_groups = {g["group_id"] for g in analysis["groups"]}
    if len(known_groups) != len(analysis["groups"]):
        raise ValueError("group_id 重复")
    for a in analysis["assignments"]:
        for m in a["memberships"]:
            if m["group_id"] not in known_groups:
                raise ValueError(f"membership 指向不存在的 group：{m['group_id']}")

    counted = {"assigned": 0, "ambiguous": 0, "residual": 0}
    for a in analysis["assignments"]:
        counted[a["disposition"]] += 1
    if counted != analysis["coverage"]:
        raise ValueError("coverage 与 assignments 不自洽")

    for g in analysis["groups"]:
        core = sum(
            1
            for a in analysis["assignments"]
            for m in a["memberships"]
            if m["group_id"] == g["group_id"] and m["role"] == "core"
        )
        if core != g["member_counts"]["core"]:
            raise ValueError(f"{g['group_id']} 的 core 计数与 memberships 不符")


def write_index(out_dir: Path, index: dict, matrix: np.ndarray) -> None:
    """索引子事务：`index.json` 与向量文件要么都发布，要么都不发布。

    半写入（JSON 在而向量不在，或反过来）会让下游读到一份说谎的索引，
    比完全没有索引更糟。
    """
    out_dir = Path(out_dir)
    written: list[Path] = []
    try:
        vectors = out_dir / "index-vectors.npy"
        np.save(vectors, matrix.astype(np.float32))
        written.append(vectors)
        payload = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=False)
        target = out_dir / "index.json"
        target.write_text(payload, encoding="utf-8")
        written.append(target)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        # np.save 会自动补 .npy 后缀，异常发生在补名之后时上面那条可能没删掉
        (out_dir / "index-vectors.npy").unlink(missing_ok=True)
        raise
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_index.py -q`
Expected: PASS（9 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/index.py tests/test_index.py
git commit -m "feat(index): index.json 组装 + 合同自检 + 原子子事务落盘

analyses 从第一天就是数组：D（residual 二次微聚类）要同时保留两套 disposition，
单顶层结构表达不了，等到那时再改是破坏性迁移，现在多写一层是零成本。

coverage 强制由 assignments 派生——独立计数迟早漂移，而漂移后没有任何测试
会发现。写盘是子事务：两个文件要么都在要么都不在，半写入的索引比没有索引更糟。"
```

---

### Task 5: 真实 embedder 适配层与 token-safe 分块

**Files:**
- Modify: `src/kb_init/embed.py`（追加适配器，**保持顶层不 import fastembed**）
- Test: `tests/test_embed_adapter.py`
- Modify: `pyproject.toml`（加 `fastembed>=0.3`）

**Interfaces:**
- Consumes: `Embedder`、`Splitter`
- Produces:
  - `DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"`、`MAX_TOKENS = 512`
  - `class FastEmbedEmbedder(model_name: str = DEFAULT_MODEL, progress=None)` — 实现 `Embedder`，**惰性导入**
  - `build_splitter(model_name: str = DEFAULT_MODEL) -> tuple[Splitter, dict]`
    返回 `(splitter, splitter_meta)`；`splitter_meta` 形如 `{"name": ..., "max_tokens": 512, "fallback_used": bool}`
  - `TokenSafeSplitter(count_tokens: Callable[[str], int], max_tokens: int = MAX_TOKENS, probe_chars: int = 400)`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_embed_adapter.py
import sys

import pytest

from kb_init.embed import MAX_TOKENS, TokenSafeSplitter, build_splitter


def test_token_safe_splitter_never_exceeds_limit_for_dense_text():
    """每 1 字符算 3 token 的极端计数器——模拟英文/代码把 400 字符撑爆 512 token。"""
    splitter = TokenSafeSplitter(count_tokens=lambda s: len(s) * 3, max_tokens=MAX_TOKENS)
    text = "x" * 2000
    spans = splitter.split(text)
    assert spans, "不该切出空结果"
    for start, end in spans:
        assert (end - start) * 3 <= MAX_TOKENS
    assert "".join(text[s:e] for s, e in spans) == text


def test_token_safe_splitter_keeps_whole_text_when_within_limit():
    splitter = TokenSafeSplitter(count_tokens=lambda s: len(s), max_tokens=MAX_TOKENS)
    text = "短文本"
    assert splitter.split(text) == [(0, len(text))]


def test_token_safe_splitter_on_empty_text():
    splitter = TokenSafeSplitter(count_tokens=len, max_tokens=MAX_TOKENS)
    assert splitter.split("") == []


def test_build_splitter_falls_back_and_says_so_when_tokenizer_unavailable(monkeypatch):
    """拿不到真 tokenizer 时必须降级并**如实记录**，不能假装是 token-safe。"""
    monkeypatch.setitem(sys.modules, "fastembed", None)
    splitter, meta = build_splitter()
    assert meta["fallback_used"] is True
    assert meta["name"] == "char"
    assert splitter.split("abc") == [(0, 3)]


def test_module_does_not_import_fastembed_at_top_level():
    """--no-index 路径与全部单测都不该因为 import 就拖进 ONNX 运行时。"""
    import subprocess

    code = "import kb_init.embed, sys; print('fastembed' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


@pytest.mark.smoke
def test_real_model_smoke(tmp_path):
    """真实模型烟测：不进常规 CI，需已预热模型缓存。

    Run: .venv/bin/python -m pytest -m smoke -q
    """
    from kb_init.embed import DEFAULT_MODEL, FastEmbedEmbedder, build_splitter

    embedder = FastEmbedEmbedder()
    vectors = list(embedder.embed(["测试文本", "second text"]))
    assert len(vectors) == 2
    assert vectors[0].shape == (512,)
    assert all(v.dtype.kind == "f" and bool(v.any()) for v in vectors)

    splitter, meta = build_splitter(DEFAULT_MODEL)
    assert meta["fallback_used"] is False
    long_text = "def f():\n    return 1\n" * 200
    for start, end in splitter.split(long_text):
        assert (end - start) > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_embed_adapter.py -q -m "not smoke"`
Expected: FAIL — `ImportError: cannot import name 'TokenSafeSplitter'`

- [ ] **Step 3: 加依赖、注册 marker、写实现**

```toml
# pyproject.toml —— dependencies 一行改成：
dependencies = ["PyYAML>=6.0", "numpy>=1.24", "scikit-learn>=1.3", "fastembed>=0.3"]

# 并追加：
[tool.pytest.ini_options]
markers = ["smoke: 需要真实模型缓存，不进常规 CI"]
addopts = "-m 'not smoke'"
```

```python
# src/kb_init/embed.py —— 在文件末尾追加
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

    def __init__(self, count_tokens, max_tokens: int = MAX_TOKENS,
                 probe_chars: int = 400) -> None:
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
                lo = pos + 1
                while lo < hi:                      # 二分找不超限的最大 end
                    mid = (lo + hi + 1) // 2
                    if self._count(text[pos:mid]) <= self._max_tokens:
                        lo = mid
                    else:
                        hi = mid - 1
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
            self.revision = str(
                getattr(self._model, "model_description", {}).get("model_file", "")
            )
        return self._model

    def embed(self, texts: list[str]):
        model = self._ensure()
        done = 0
        for vec in model.embed(texts):
            done += 1
            if self._progress and done % 200 == 0:
                self._progress({"event": "embedding", "done": done, "total": len(texts)})
            yield vec
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_embed_adapter.py -q`
Expected: PASS（5 passed，smoke 被 addopts 默认排除）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/embed.py tests/test_embed_adapter.py pyproject.toml
git commit -m "feat(embed): token-safe 分块 + fastembed 惰性适配器

400 字符是中文近似 1 字 1 token 的启发式，英文/代码会在 400 字符内突破
512 token——那正是 DESIGN §7 那条硬约束要防的事，用启发式挡它等于没挡。
改为按真实 tokenizer 计数二分切分；拿不到 tokenizer 时降级为字符切分，
但必须在 method.splitter.fallback_used 里如实记录，不许假装是 token-safe。

fastembed 全程惰性导入，并加一条子进程测试钉死「import kb_init.embed 之后
sys.modules 里没有 fastembed」——否则 --no-index 快速通道会白白拖进 ONNX 运行时。"
```

---

### Task 6: 接入管线、manifest 状态与退出码 5

**Files:**
- Modify: `src/kb_init/pipeline.py`
- Modify: `src/kb_init/manifest.py`
- Modify: `src/kb_init/cli.py`
- Test: `tests/test_index_pipeline.py`

**Interfaces:**
- Consumes: `chunk_documents`、`CharSplitter`、`build_splitter`、`FastEmbedEmbedder`、`pool_chunk_vectors`、`cluster_documents`、`build_index`、`build_time_axis`、`validate_index`、`write_index`
- Produces:
  - `run(..., no_index: bool = False, embedder=None, splitter=None) -> dict`
    返回值在 Plan 1 的 counts 基础上追加 `index_status`（`complete`/`failed`/`skipped`）与 `index_reason`
  - `write_manifest(..., index_status: str = "skipped", index_reason: str | None = None)`
  - CLI 新增 `--no-index`；`index_status == "failed"` → 退出码 5

- [ ] **Step 1: 写失败测试**

```python
# tests/test_index_pipeline.py
import json

import pytest

from kb_init.cli import main
from kb_init.pipeline import run
from tests.fakes import FakeEmbedder

LONG = "内容" * 110


def _corpus(root, n=14):
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / f"doc{i:02d}.md").write_text(
            f"# 标题{i}\n\n{LONG}第{i}篇", encoding="utf-8"
        )


def test_index_is_written_and_bound_to_manifest(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    counts = run(src, out, run_id="idx", embedder=FakeEmbedder(dim=8))

    assert counts["index_status"] == "complete"
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert index["corpus_hash"] == manifest["corpus_hash"]
    assert manifest["index_status"] == "complete"
    assert (out / "index-vectors.npy").exists()

    kept = [d["doc_id"] for d in manifest["documents"] if d["status"] == "kept"]
    assigned = [a["doc_id"] for a in index["analyses"][0]["assignments"]]
    assert sorted(assigned) == sorted(kept)


def test_time_axis_is_unavailable_when_dates_are_missing(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    run(src, out, run_id="idx2", embedder=FakeEmbedder(dim=8))
    ta = json.loads((out / "index.json").read_text(encoding="utf-8"))["analyses"][0]["time_axis"]
    assert ta["available"] is False
    assert ta["total_docs"] == 14


def test_no_index_publishes_cleaned_output_without_index(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    counts = run(src, out, run_id="idx3", no_index=True)

    assert counts["index_status"] == "skipped"
    assert (out / "knowledge").is_dir()
    assert not (out / "index.json").exists()
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["index_status"] == "skipped"


def test_index_failure_still_publishes_cleaned_output(tmp_path):
    """这是本任务的核心：索引炸了不能把清洗产物一起带走。"""
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"

    class Exploding:
        def embed(self, texts):
            raise RuntimeError("模型下载失败")

    counts = run(src, out, run_id="idx4", embedder=Exploding())

    assert counts["index_status"] == "failed"
    assert counts["kept"] > 0
    assert (out / "knowledge").is_dir() and any((out / "knowledge").iterdir())
    assert not (out / "index.json").exists()
    assert not (out / "index-vectors.npy").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["index_status"] == "failed"
    assert manifest["index_reason"]


def test_cli_returns_5_when_index_failed(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"

    def fake_run(*a, **k):
        return {"total": 14, "kept": 14, "dropped_stub": 0, "dropped_duplicate": 0,
                "index_status": "failed", "index_reason": "model_unavailable"}

    monkeypatch.setattr("kb_init.pipeline.run", fake_run)
    assert main([str(src), "-o", str(out)]) == 5


def test_cli_no_index_flag_returns_zero(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-index"]) == 0


def test_keyboard_interrupt_is_not_swallowed_as_partial_success(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"

    class Interrupting:
        def embed(self, texts):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(src, out, run_id="idx5", embedder=Interrupting())
    assert not out.exists()          # staging 被清理，不留半成品
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_index_pipeline.py -q`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'embedder'`

- [ ] **Step 3: 写实现**

在 `src/kb_init/manifest.py` 的 `write_manifest` 签名末尾追加两个参数，并写进 payload：

```python
def write_manifest(
    docs, out_dir, *, run_id, source, unresolved_links, skipped_inputs,
    index_status: str = "skipped", index_reason: str | None = None,
):
    ...
    payload = {
        ...,
        # 只看「有没有 index.json」分不清 skipped / failed / 旧版本产物，
        # 事后诊断不能只靠 stderr 和退出码。
        "index_status": index_status,
        "index_reason": index_reason,
    }
```

在 `src/kb_init/pipeline.py` 中，于 `write_manifest` **之前**插入索引阶段：

```python
def _run_index_stage(staging, docs, embedder, splitter):
    """在 staging 内构建索引。返回 (status, reason)。

    **失败必须在这里被吸收成状态**：Plan 1 的 ExitStack 注册了
    `published or rmtree(staging)`，任何在 rename 之前传播出去的异常都会
    连清洗产物一起删掉——那样 CLI 再返回退出码 5 就是在撒谎。
    """
    from kb_init.chunk import chunk_documents
    from kb_init.cluster import cluster_documents
    from kb_init.embed import pool_chunk_vectors
    from kb_init.index import (
        build_index, build_time_axis, validate_index, write_index,
    )
    from kb_init import __version__

    kept = [d for d in docs if d.status == "kept"]
    if not kept:
        return "complete", None

    try:
        if splitter is None:
            from kb_init.embed import build_splitter
            splitter, splitter_meta = build_splitter()
        else:
            splitter_meta = {"name": "injected", "max_tokens": 512,
                             "fallback_used": False}
        if embedder is None:
            from kb_init.embed import DEFAULT_MODEL, FastEmbedEmbedder
            embedder = FastEmbedEmbedder()
            model_name = DEFAULT_MODEL
        else:
            model_name = getattr(embedder, "model_name", "injected")

        chunks = chunk_documents([(d.doc_id, d.body) for d in kept], splitter)
        texts = {d.doc_id: d.body for d in kept}
        vectors = list(embedder.embed(
            [texts[c.doc_id][c.start:c.end] for c in chunks]
        ))
        doc_ids, matrix = pool_chunk_vectors(chunks, vectors)

        # 没切出块的文档（空正文）拿不到向量，必须显式补一条 residual，
        # 否则「每个 kept doc 恰有一条 assignment」这条合同会被悄悄破坏。
        groups, assignments = cluster_documents(doc_ids, matrix)
        from kb_init.cluster import Assignment
        missing = sorted({d.doc_id for d in kept} - set(doc_ids))
        assignments = list(assignments) + [
            Assignment(d, "residual", (), "empty_document") for d in missing
        ]

        dated = sum(1 for d in kept if d.date_source not in ("unknown", "unresolved"))
        index = build_index(
            run_id=run_id_of(docs) if False else _RUN_ID_PLACEHOLDER,
            corpus_hash=_CORPUS_HASH_PLACEHOLDER,
            chunks=chunks, groups=groups, assignments=assignments,
            method={
                "family": "density", "name": "hdbscan",
                "model": model_name,
                "model_revision": getattr(embedder, "revision", ""),
                "params": {"min_cluster_size": 5, "min_samples": 5,
                           "metric": "euclidean"},
                "seed": 0, "splitter": splitter_meta, "pooling": "mean_l2",
                "score_kind": "density_membership",
                "score_direction": "higher_better", "decision_threshold": None,
            },
            time_axis=build_time_axis(dated, len(kept)),
            versions={"kb_init": __version__},
        )
        validate_index(index, [d.doc_id for d in kept])
        write_index(staging, index, matrix)
        return "complete", None
    except Exception as exc:            # 不接 BaseException：KeyboardInterrupt 必须透传
        for name in ("index.json", "index-vectors.npy"):
            (staging / name).unlink(missing_ok=True)
        return "failed", type(exc).__name__
```

> **实现说明**：上面的 `_RUN_ID_PLACEHOLDER` / `_CORPUS_HASH_PLACEHOLDER` 是本计划的记法，
> 实现时把 `run_id` 与 `compute_corpus_hash(docs)` 作为参数传进 `_run_index_stage`，
> 与 `write_manifest` 用的是**同一对值**（下游靠 `corpus_hash` fail closed）。

`run()` 的改动：

```python
def run(source, out_dir, wikilinks=False, run_id=None,
        no_index=False, embedder=None, splitter=None) -> dict:
    ...
    result = emit(docs, staging, wikilinks=wikilinks)
    if no_index:
        index_status, index_reason = "skipped", None
    else:
        index_status, index_reason = _run_index_stage(
            staging, docs, embedder, splitter, run_id=run_id,
            corpus_hash=compute_corpus_hash(docs),
        )
    write_manifest(
        docs, staging, run_id=run_id, source=str(source),
        unresolved_links=result.unresolved_links, skipped_inputs=collisions,
        index_status=index_status, index_reason=index_reason,
    )
    ...
    staging.rename(out_dir)      # ← commit 点
    published = True
    summary = summarize(docs)
    summary["index_status"] = index_status
    summary["index_reason"] = index_reason
    return summary               # CLI 据此映射退出码，绝不在 commit 点之后 raise
```

`cli.py` 的改动：

```python
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="跳过索引（不下载模型、不联网），只产出清洗结果",
    )
    ...
    counts = run(args.source, args.out, wikilinks=args.wikilinks,
                 no_index=args.no_index)
    ...
    print(f"输出目录：{args.out}")
    if counts.get("index_status") == "failed":
        print(
            f"警告：清洗产物已写入，但索引未完成（{counts.get('index_reason')}）。"
            f"换个 --out 目录重跑即可只补索引。",
            file=sys.stderr,
        )
        return 5
    return 0
```

- [ ] **Step 4: 运行全量测试确认通过**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（既有 93 项 + 本轮新增全部通过）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/pipeline.py src/kb_init/manifest.py src/kb_init/cli.py tests/test_index_pipeline.py
git commit -m "feat(pipeline): 索引接入主流程，失败被吸收为状态而非异常

关键控制流：索引失败必须在 pipeline 内被吸收。Plan 1 的 ExitStack 注册了
published or rmtree(staging)，任何在 rename 之前传播出去的异常都会连清洗产物
一起删掉——那样 CLI 再返回退出码 5 就是在撒谎。

因此：窄边界 except Exception（不接 BaseException，KeyboardInterrupt 必须透传）
→ 回滚 index 半成品 → manifest 记 index_status/index_reason → 唯一一次 rename
→ CLI 在 run() 正常返回后映射退出码 5。

manifest 记状态而非靠「有没有 index.json」推断：那分不清 skipped / failed /
旧版本产物，事后诊断不能只靠 stderr。"
```

---

### Task 7: 真实语料验收与文档同步

**Files:**
- Modify: `tests/test_real_corpus.py`
- Modify: `README.md`
- Modify: `docs/DESIGN.md`
- Modify: `STATUS.md`

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 无新接口

- [ ] **Step 1: 写失败测试**

```python
# tests/test_real_corpus.py —— 追加
@pytest.mark.skipif(not NOTION.exists(), reason="Notion 语料不在本机")
def test_notion_index_time_axis_unavailable(tmp_path):
    """真实导出语料上时间轴必须自动降级——这是 §2.2 条件门的验收。"""
    import json
    from tests.fakes import FakeEmbedder

    out = tmp_path / "out"
    counts = run(NOTION, out, run_id="acceptance-index", embedder=FakeEmbedder(dim=16))
    assert counts["index_status"] == "complete"

    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    analysis = index["analyses"][0]
    ta = analysis["time_axis"]
    assert ta["available"] is False, f"日期覆盖率 {ta['coverage']:.1%} 不该触发时间轴"
    assert sum(analysis["coverage"].values()) == counts["kept"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_real_corpus.py -q`
Expected: FAIL（`run()` 尚未接受 `embedder`，或断言不成立）——若 Task 6 已完成则应直接 PASS，此时改为确认它**确实在跑**（`-v` 看到用例名，不是 skipped）

- [ ] **Step 3: 同步文档**

`README.md` 退出码表追加一行：

```markdown
| 5 | 清洗产物已发布，但索引未完成（换个 `--out` 目录重跑即可只补索引） |
```

`README.md` 选项表追加一行：

```markdown
| `--no-index` | 跳过索引：不下载模型、不联网，几秒拿到清洗产物。索引首次运行需下载 ~90MB 模型并按分钟计 |
```

`docs/DESIGN.md` §7「L1/L2 纯本地，无需 key」一行的理由列改为：

```markdown
| L1/L2 | 纯本地，无需 key | 免费预览层，隐私。**清洗秒出；索引首次运行需下载 ~90MB 模型并按分钟计**——此前写的"秒出"只对清洗成立，对索引不成立 |
```

`docs/DESIGN.md` §5「L2 轨迹（本地，无 key）」小节开头追加：

```markdown
> ⚠️ **三类时间轴洞察（兴趣迁移曲线 / 半衰期 / 沉默主题）受日期覆盖率条件门约束。**
> 实测导出类语料的日期可解析率只有 5–6%（根因是导出包里就没有，见 2A spec §2.2），
> 低于阈值时索引层会置 `time_axis.available=false`，这三类洞察自动不产出。
> 只有"留存率"不依赖时间轴。
```

`STATUS.md` 的「当前阶段」改为反映 2A 完成、下一步是 2B。

- [ ] **Step 4: 跑完整验收**

```bash
.venv/bin/python -m pytest -q                      # 全量，必须全绿
.venv/bin/python -m pytest -m smoke -q             # 真实模型烟测（需已预热缓存）
uv run --with fastembed --with scikit-learn --with numpy --with socksio \
  probes/cluster_quality_probe.py <真实产物目录> -k 8 --hdbscan 5
```
人工确认：`index.json` 的 groups 与探针给出的簇一致，且至少 3 个簇能被一句话命名。

- [ ] **Step 5: 提交**

```bash
git add tests/test_real_corpus.py README.md docs/DESIGN.md STATUS.md
git commit -m "docs+test: 2A 真实语料验收与文档同步

README 补退出码 5 与 --no-index；DESIGN §7 把「秒出」改成只对清洗成立的
诚实表述；§5 标注三类时间轴洞察受条件门约束（实测导出类语料日期覆盖率仅 5-6%）。"
```

---

## Self-Review

**1. Spec 覆盖检查**

| spec 条款 | 落在哪个任务 |
|---|---|
| §2.1 只实现 HDBSCAN core-only | Task 3 |
| §2.2 时间轴条件门 + 阈值 0.30 | Task 4（`build_time_axis`）+ Task 6（接线）+ Task 7（真实语料验收） |
| §2.3 `--no-index` + 索引进主流程 | Task 6 |
| §2.4 不给簇起名 | Task 3（`Group` 无 label 字段） |
| §3 模块边界 / `index.py` 唯一写盘 | Task 1–4 |
| §3.1 两个协议 + token-safe 分块 + 偏移单位 | Task 1（协议 + 偏移）+ Task 5（token-safe） |
| §3.2 进度走 callback 不直接打印 | Task 5（`FastEmbedEmbedder(progress=...)`） |
| §5 `analyses[]` / role counts / representatives / score_direction | Task 3（产出）+ Task 4（组装与校验） |
| §5 每个 kept doc 恰有一条 assignment | Task 4（`validate_index`）+ Task 6（补 `empty_document` residual） |
| §6 向量产物 + 行序 doc_id 升序 | Task 2（行序）+ Task 4（落盘） |
| §7.1 失败吸收控制流 + 子事务 | Task 4（`write_index` 回滚）+ Task 6（阶段吸收） |
| §7.2 失败模式表 | Task 2（非法产出）+ Task 3（语料过小）+ Task 4（写盘回滚）+ Task 6（其余） |
| §8 三层测试网 | Task 1–4（第一层）+ Task 5（smoke lane）+ Task 6（故障注入） |
| §9 文档变更项 5 条 | Task 7（§13 那条已在 spec 阶段单独提交） |
| §10 验收标准 6 条 | Task 6（1/2/4）+ Task 7（3/5/6） |

无缺口。

**2. 占位符扫描**

`_RUN_ID_PLACEHOLDER` / `_CORPUS_HASH_PLACEHOLDER` 出现在 Task 6 的示意代码里，**紧跟着的实现说明
已写明它们是记法**：实现时把 `run_id` 与 `compute_corpus_hash(docs)` 作为参数传进
`_run_index_stage`，与 `write_manifest` 用同一对值。除此之外无 TBD / TODO / "类似 Task N"。

**3. 类型一致性**

- `Chunk(chunk_id, doc_id, start, end)` — Task 1 定义，Task 2/4/6 一致引用。
- `pool_chunk_vectors(chunks, vectors) -> (list[str], np.ndarray)` — Task 2 定义，Task 6 按 `(doc_ids, matrix)` 解包，一致。
- `cluster_documents(doc_ids, matrix, *, min_cluster_size, min_samples) -> (list[Group], list[Assignment])` — Task 3 定义，Task 6 一致。
- `Assignment(doc_id, disposition, memberships, reason_code)` — Task 3 定义；Task 6 构造 `empty_document` residual 时用同一顺序。
- `build_index(...)` 全部为关键字参数，Task 4 定义与 Task 6 调用逐字对应。
- `write_manifest(..., index_status, index_reason)` — Task 6 同时改签名与调用方。
- `Group.member_counts` 的键 `core/halo/micro/total_docs` 在 Task 3 产出、Task 4 校验（只校验 `core`）、spec §5 三处一致。
