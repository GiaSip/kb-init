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
