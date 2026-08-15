"""过大簇的检测与二次细分。只吃向量与 doc_id，**不认识文本**。

「多大算过大」不用篇数比例这种只能在手上这几份语料上调出来的魔数，改用语料
自校准的判据：把簇的内聚度与**本语料 residual 集合**的内聚度相比。residual
按定义就是「没有主题的一堆」，它天然是这份语料的无主题基线。
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

# 实测：六个正常簇落在 +0.18…+0.23，一个 509 篇的大杂烩落在 +0.069，中间是空的。
# 阈值取在空档里——与 2A 给 time_axis 定 0.30 是同一条依据，不是调参结果。
COHESION_LIFT_MIN = 0.12


def cohesion(rows: np.ndarray) -> float:
    """成员向量到其质心的平均余弦。输入必须是已 L2 归一的行向量。"""
    rows = np.asarray(rows, dtype=np.float64)
    if rows.ndim != 2 or rows.shape[0] < 2:
        raise ValueError("内聚度至少需要两行向量")
    centroid = rows.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm == 0:
        return 0.0
    return float((rows @ (centroid / norm)).mean())


def group_lifts(
    members_by_group: Mapping[str, Sequence[str]],
    residual_ids: Sequence[str],
    rows: Mapping[str, np.ndarray],
) -> dict[str, float]:
    """每个 group 的内聚度相对 residual 基线的提升量。

    residual 不足两篇时**返回空字典**：没有基线就不判，而不是拿 0 当基线——
    那会把所有簇都判为「远高于基线」，检测器就永远不会说不。
    """
    baseline_rows = [rows[d] for d in residual_ids if d in rows]
    if len(baseline_rows) < 2:
        return {}
    baseline = cohesion(np.vstack(baseline_rows))
    lifts: dict[str, float] = {}
    for group_id, members in members_by_group.items():
        member_rows = [rows[d] for d in members if d in rows]
        if len(member_rows) < 2:
            continue
        lifts[group_id] = cohesion(np.vstack(member_rows)) - baseline
    return lifts


def flagged_groups(
    lifts: Mapping[str, float], lift_min: float = COHESION_LIFT_MIN
) -> list[str]:
    """内聚度没比「未分类堆」高出多少的 group——它不是一个主题。"""
    return sorted(g for g, lift in lifts.items() if lift < lift_min)
