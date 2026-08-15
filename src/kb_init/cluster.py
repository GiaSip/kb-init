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
    if len(set(doc_ids)) != len(doc_ids):
        # 排序键必须唯一，否则下面「先排序再聚类」给出的顺序不确定，
        # 「打乱输入结果不变」这条保证也就不成立了。
        raise ValueError("doc_ids 存在重复")
    if len(doc_ids) < min_cluster_size * MIN_DOCS_FACTOR:
        return [], _all_residual(doc_ids, "corpus_too_small")

    # 先按 doc_id 排序再聚类：HDBSCAN 对输入顺序不是完全不敏感，排序把
    # 「打乱输入结果不变」变成结构性保证，而不是碰运气。
    order = sorted(range(len(doc_ids)), key=lambda i: doc_ids[i])
    sorted_ids = [doc_ids[i] for i in order]
    sorted_matrix = np.ascontiguousarray(matrix[order])

    # copy=True 不是为了消警告：默认的 copy=False 允许 HDBSCAN 原地改写输入矩阵，
    # 而 fit_predict 之后我们还要用同一个矩阵算 medoid——那样算出来的代表物
    # 就是基于被改写过的向量，且不会有任何测试发现。
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        copy=True,
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
    ordered = sorted(members_of.values(), key=lambda ms: (-len(ms), ms))
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
    assignments: list[Assignment] = []
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
