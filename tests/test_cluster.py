import numpy as np

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

    assert [(g.group_id, g.member_counts) for g in g1] == [
        (g.group_id, g.member_counts) for g in g2
    ]
    assert [g.representatives for g in g1] == [g.representatives for g in g2]

    def shape(assignments):
        return [
            (a.doc_id, a.disposition, [mm.group_id for mm in a.memberships])
            for a in sorted(assignments, key=lambda x: x.doc_id)
        ]

    assert shape(a1) == shape(a2)


def test_corpus_too_small_is_not_an_error():
    ids = ["d1", "d2", "d3"]
    m = np.eye(3, 8, dtype=np.float32)
    groups, assignments = cluster_documents(ids, m, min_cluster_size=5, min_samples=5)
    assert groups == []
    assert {a.disposition for a in assignments} == {"residual"}
    assert {a.reason_code for a in assignments} == {"corpus_too_small"}


def test_residual_docs_carry_empty_memberships_and_reason():
    ids, m = _two_blobs(n=8)
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


def test_group_ids_do_not_reuse_hdbscan_raw_labels():
    """簇号按成员集合重编号，从 g01 起连续——原始 label 依赖内部遍历顺序。"""
    ids, m = _two_blobs()
    groups, _ = cluster_documents(ids, m, min_cluster_size=5, min_samples=3)
    assert [g.group_id for g in groups] == ["g01", "g02"]


def test_duplicate_doc_ids_are_rejected():
    """排序键必须唯一，否则「打乱输入结果不变」的保证不成立。"""
    import pytest

    m = np.eye(4, 8, dtype=np.float32)
    with pytest.raises(ValueError, match="重复"):
        cluster_documents(["d1", "d1", "d2", "d3"], m, min_cluster_size=2, min_samples=1)


def test_permutation_invariance_compares_full_objects():
    """只比 doc_id/disposition/group_id 不够——role、score、reason_code 也必须一致。"""
    ids, m = _two_blobs()
    g1, a1 = cluster_documents(ids, m, min_cluster_size=5, min_samples=3)
    order = np.random.default_rng(11).permutation(len(ids))
    g2, a2 = cluster_documents([ids[i] for i in order], m[order],
                               min_cluster_size=5, min_samples=3)
    assert g1 == g2
    assert sorted(a1, key=lambda a: a.doc_id) == sorted(a2, key=lambda a: a.doc_id)


def _blobs(centres, per_blob=6, jitter=0.01):
    """围绕给定中心生成确定性的小簇，不用随机数——测试不能靠运气。"""
    ids, rows = [], []
    for c_idx, centre in enumerate(centres):
        for k in range(per_blob):
            v = np.array(centre, dtype=np.float32).copy()
            v[c_idx % len(centre)] += jitter * (k + 1)
            v /= np.linalg.norm(v)
            ids.append(f"d{c_idx}{k:02d}")
            rows.append(v)
    return ids, np.vstack(rows)


def test_group_id_prefix_is_applied():
    ids, matrix = _blobs([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    groups, _ = cluster_documents(ids, matrix, group_id_prefix="g01s")
    assert groups, "前缀测试需要至少一个簇，否则断言恒真"
    assert all(g.group_id.startswith("g01s") for g in groups)
    assert len({g.group_id for g in groups}) == len(groups)


def test_default_prefix_and_method_unchanged():
    ids, matrix = _blobs([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    groups, _ = cluster_documents(ids, matrix)
    assert groups and groups[0].group_id == "g01"


def test_leaf_method_is_accepted_and_deterministic():
    ids, matrix = _blobs([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    first = cluster_documents(ids, matrix, cluster_selection_method="leaf")
    second = cluster_documents(ids, matrix, cluster_selection_method="leaf")
    assert [g.group_id for g in first[0]] == [g.group_id for g in second[0]]
    assert [(a.doc_id, a.disposition) for a in first[1]] == \
           [(a.doc_id, a.disposition) for a in second[1]]
    assert len(first[0]) >= 2, "确定性断言需要真的聚出簇，否则两边都空也相等"
