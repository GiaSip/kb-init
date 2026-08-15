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
    index, _ = _fixture()
    validate_index(index, ["d1", "d2"])


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
