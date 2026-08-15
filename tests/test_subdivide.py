import numpy as np
import pytest

from kb_init.subdivide import (
    COHESION_LIFT_MIN,
    cohesion,
    flagged_groups,
    group_lifts,
    subdivide_group,
)


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _rows(spec):
    """spec: {doc_id: 向量}，一律 L2 归一（与 embed.py 的输出契约一致）"""
    return {k: _unit(v) for k, v in spec.items()}


def test_cohesion_of_identical_vectors_is_one():
    rows = np.vstack([_unit([1.0, 0.0, 0.0])] * 4)
    assert cohesion(rows) == pytest.approx(1.0, abs=1e-6)


def test_cohesion_of_orthogonal_spread_is_lower():
    rows = np.vstack([_unit([1.0, 0.0, 0.0]), _unit([0.0, 1.0, 0.0]),
                      _unit([0.0, 0.0, 1.0])])
    assert cohesion(rows) == pytest.approx(0.5774, abs=1e-3)


def test_cohesion_needs_at_least_two_rows():
    with pytest.raises(ValueError):
        cohesion(np.vstack([_unit([1.0, 0.0, 0.0])]))


def test_lift_separates_tight_group_from_scattered_group():
    # tight：三篇几乎同向。blob：三篇互相正交（与 residual 一样散）
    rows = _rows({
        "t1": [1.0, 0.02, 0.0], "t2": [1.0, 0.0, 0.03], "t3": [0.99, 0.01, 0.01],
        "b1": [1.0, 0.0, 0.0],  "b2": [0.0, 1.0, 0.0],  "b3": [0.0, 0.0, 1.0],
        "r1": [1.0, 0.0, 0.0],  "r2": [0.0, 1.0, 0.0],  "r3": [0.0, 0.0, 1.0],
    })
    lifts = group_lifts({"g01": ["t1", "t2", "t3"], "g02": ["b1", "b2", "b3"]},
                        ["r1", "r2", "r3"], rows)
    assert lifts["g01"] > COHESION_LIFT_MIN          # 正例：紧致簇必须通过
    assert lifts["g02"] < COHESION_LIFT_MIN          # 负例：与基线同散的簇必须被标记
    assert flagged_groups(lifts) == ["g02"]


def test_no_group_is_flagged_when_all_are_tight():
    """负例的负例：检测器不能把所有簇都判为过大——一个恒返回 True 的检测器
    也能让「巨簇被标记」那条测试全绿。"""
    rows = _rows({
        "a1": [1.0, 0.01, 0.0], "a2": [1.0, 0.0, 0.02],
        "b1": [0.0, 1.0, 0.01], "b2": [0.01, 1.0, 0.0],
        "r1": [1.0, 0.0, 0.0],  "r2": [0.0, 1.0, 0.0], "r3": [0.0, 0.0, 1.0],
    })
    lifts = group_lifts({"g01": ["a1", "a2"], "g02": ["b1", "b2"]},
                        ["r1", "r2", "r3"], rows)
    assert flagged_groups(lifts) == []
    assert len(lifts) == 2                            # 防「返回空 dict」让上面恒真


def test_empty_residual_baseline_flags_nothing():
    """residual 为空时没有可比基线。宁可不判，也不要拿 0 当基线把所有簇判为通过。"""
    rows = _rows({"a1": [1.0, 0.0, 0.0], "a2": [0.0, 1.0, 0.0]})
    lifts = group_lifts({"g01": ["a1", "a2"]}, [], rows)
    assert lifts == {}
    assert flagged_groups(lifts) == []


def _two_tight_blobs(n=6):
    rows, ids = {}, []
    for i in range(n):
        for axis, tag in ((0, "a"), (1, "b")):
            v = np.zeros(3, dtype=np.float32)
            v[axis] = 1.0
            v[2] = 0.001 * i
            v /= np.linalg.norm(v)
            doc = f"{tag}{i:02d}"
            rows[doc] = v
            ids.append(doc)
    return ids, rows


def test_subdivision_splits_a_blob_into_passing_children():
    ids, rows = _two_tight_blobs()
    baseline = 0.3                                   # 远低于两个团各自的内聚度
    groups, assignments = subdivide_group("g01", ids, rows, baseline,
                                          min_cluster_size=3, min_samples=3)
    assert len(groups) >= 2, "只产出一个子簇时下面的断言会恒真"
    assert all(g.group_id.startswith("g01s") for g in groups)
    assert sorted(a.doc_id for a in assignments) == sorted(ids)


def test_children_failing_the_detector_fold_back_to_residual():
    ids, rows = _two_tight_blobs()
    baseline = 0.999                                 # 高到没有子簇能通过
    groups, assignments = subdivide_group("g01", ids, rows, baseline,
                                          min_cluster_size=3, min_samples=3)
    assert groups == []
    assert len(assignments) == len(ids)              # 防「返回空列表」让下面恒真
    assert all(a.disposition == "residual" for a in assignments)
    assert {a.reason_code for a in assignments} <= {
        "subdivision_rejected", "under_differentiated_parent"}


def test_assignments_never_reference_a_dropped_child_group():
    ids, rows = _two_tight_blobs()
    groups, assignments = subdivide_group("g01", ids, rows, 0.3,
                                          min_cluster_size=3, min_samples=3)
    known = {g.group_id for g in groups}
    referenced = {m.group_id for a in assignments for m in a.memberships}
    assert referenced, "没有任何 membership 时这条断言恒真"
    assert referenced <= known


def test_member_counts_match_actual_memberships():
    ids, rows = _two_tight_blobs()
    groups, assignments = subdivide_group("g01", ids, rows, 0.3,
                                          min_cluster_size=3, min_samples=3)
    assert len(groups) >= 2, "细分退化成空时下面的循环恒真"
    for g in groups:
        actual = sum(1 for a in assignments
                     for m in a.memberships if m.group_id == g.group_id)
        assert actual > 0
        assert g.member_counts["total_docs"] == actual
        assert g.member_counts["core"] == actual
