import numpy as np
import pytest

from kb_init.subdivide import COHESION_LIFT_MIN, cohesion, flagged_groups, group_lifts


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
