import json
import pathlib

import numpy as np
import pytest

from kb_init.chunk import Chunk
from kb_init.cluster import Assignment, Group, Membership
from kb_init.index import build_index, build_time_axis, validate_index, write_index


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
        vector_doc_ids=["d1", "d2"],
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


def test_time_axis_available_above_threshold():
    ta = build_time_axis(200, 470)          # 已维护 Wiki 的实测比例 43%
    assert ta["available"] is True


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


def test_validate_accepts_a_well_formed_index():
    index, matrix = _fixture()
    validate_index(index, ["d1", "d2"], matrix)


def test_validate_rejects_doc_without_assignment():
    index, _ = _fixture()
    with pytest.raises(ValueError, match="恰有一条"):
        validate_index(index, ["d1", "d2", "d3"])


def test_validate_rejects_membership_pointing_at_unknown_group():
    index, _ = _fixture()
    index["analyses"][0]["assignments"][0]["memberships"][0]["group_id"] = "g99"
    with pytest.raises(ValueError, match="不存在的 group"):
        validate_index(index, ["d1", "d2"])


def test_validate_rejects_coverage_drift():
    index, _ = _fixture()
    index["analyses"][0]["coverage"]["residual"] = 99
    with pytest.raises(ValueError, match="不自洽"):
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
    real_write = pathlib.Path.write_text

    def boom(self, *a, **k):
        if self.name.endswith(".json"):
            raise OSError("磁盘满了")
        return real_write(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    with pytest.raises(OSError):
        write_index(tmp_path, index, matrix)
    assert list(tmp_path.iterdir()) == []


def test_validate_rejects_residual_carrying_membership():
    """结构合法但语义撒谎：标 residual 却带着 membership。"""
    index, _ = _fixture()
    a = index["analyses"][0]["assignments"][1]
    a["memberships"] = [{"group_id": "g01", "role": "core", "score": 0.5}]
    with pytest.raises(ValueError, match="residual 却带着"):
        validate_index(index, ["d1", "d2"])


def test_validate_rejects_assigned_without_membership():
    index, _ = _fixture()
    index["analyses"][0]["assignments"][0]["memberships"] = []
    with pytest.raises(ValueError, match="assigned 却没有"):
        validate_index(index, ["d1", "d2"])


def test_validate_rejects_illegal_role_and_score():
    index, _ = _fixture()
    index["analyses"][0]["assignments"][0]["memberships"][0]["role"] = "bogus"
    with pytest.raises(ValueError, match="非法 role"):
        validate_index(index, ["d1", "d2"])

    index, _ = _fixture()
    index["analyses"][0]["assignments"][0]["memberships"][0]["score"] = float("nan")
    with pytest.raises(ValueError, match="有限数"):
        validate_index(index, ["d1", "d2"])


def test_validate_rejects_representative_outside_its_group():
    index, _ = _fixture()
    index["analyses"][0]["groups"][0]["representatives"] = [
        {"doc_id": "d2", "kind": "medoid"}
    ]
    with pytest.raises(ValueError, match="不是本簇成员"):
        validate_index(index, ["d1", "d2"])


def test_validate_rejects_vector_row_count_mismatch():
    index, _ = _fixture()
    with pytest.raises(ValueError, match="向量行数"):
        validate_index(index, ["d1", "d2"], np.eye(5, 4, dtype=np.float32))


def test_validate_rejects_non_finite_matrix():
    index, matrix = _fixture()
    matrix = matrix.copy()
    matrix[0, 0] = np.inf
    with pytest.raises(ValueError, match="NaN 或 Inf"):
        validate_index(index, ["d1", "d2"], matrix)


def test_validate_rejects_chunk_offset_out_of_range():
    index, _ = _fixture()
    with pytest.raises(ValueError, match="越界"):
        validate_index(index, ["d1", "d2"], None, {"d1": "ab", "d2": "abcd"})


def test_validate_rejects_duplicate_chunk_ids():
    index, _ = _fixture()
    index["chunks"][1]["chunk_id"] = index["chunks"][0]["chunk_id"]
    with pytest.raises(ValueError, match="chunk_id 重复"):
        validate_index(index, ["d1", "d2"])


def test_time_axis_per_group_computed_only_when_available():
    from kb_init.cluster import Assignment, Group, Membership

    groups = [Group("g01", "semantic_topic",
                    {"core": 2, "halo": 0, "micro": 0, "total_docs": 2},
                    [{"doc_id": "d1", "kind": "medoid"}])]
    assignments = [
        Assignment("d1", "assigned", (Membership("g01", "core", 0.9),), None),
        Assignment("d2", "assigned", (Membership("g01", "core", 0.8),), None),
    ]
    dates = {"d1": "2024-03-01", "d2": "2025-06-30"}

    high = build_time_axis(2, 2, dates_by_doc=dates, groups=groups,
                           assignments=assignments)
    assert high["available"] is True
    assert high["per_group"] == [
        {"group_id": "g01", "dated_docs": 2, "total_docs": 2,
         "earliest": "2024-03-01", "latest": "2025-06-30"}
    ]

    low = build_time_axis(1, 100, dates_by_doc=dates, groups=groups,
                          assignments=assignments)
    assert low["available"] is False
    assert low["per_group"] is None, "覆盖率不够时不给每簇统计，免得下游拿 1% 当整体讲"


def test_validate_rejects_vector_doc_ids_disagreeing_with_chunks():
    """数量对得上但装的是另一批 doc_id——行归属整体错位，且没有任何症状。"""
    index, matrix = _fixture()
    index["vector_doc_ids"] = ["d2", "d1"]      # 集合相同，顺序不同：应通过
    validate_index(index, ["d1", "d2"], matrix)

    index["chunks"] = [c for c in index["chunks"] if c["doc_id"] == "d1"]
    with pytest.raises(ValueError, match="有块的文档集合不一致"):
        validate_index(index, ["d1", "d2"], matrix)


def test_validate_rejects_one_dimensional_matrix():
    index, _ = _fixture()
    with pytest.raises(ValueError, match="二维"):
        validate_index(index, ["d1", "d2"], np.zeros(2, dtype=np.float32))


def test_validate_rejects_wrong_dtype_even_when_empty():
    index, _ = _fixture()
    index["vector_doc_ids"] = []
    index["chunks"] = []
    with pytest.raises(ValueError, match="float32"):
        validate_index(index, ["d1", "d2"], np.zeros((0, 0), dtype=np.float64))
