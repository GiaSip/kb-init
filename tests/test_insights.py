from kb_init.insights import (
    build_corpus_insights,
    effective_residual_ids,
    presentation_groups,
)


def _index(analyses):
    return {"schema_version": "0.1", "run_id": "r", "corpus_hash": "c",
            "vector_doc_ids": [], "chunks": [], "analyses": analyses}


def _analysis(aid, parent, scope, groups, assignments):
    return {"analysis_id": aid, "parent_analysis_id": parent, "input_scope": scope,
            "method": {"params": {}}, "groups": groups, "assignments": assignments,
            "coverage": {"assigned": 0, "ambiguous": 0, "residual": 0},
            "time_axis": {"available": False, "dated_docs": 1, "total_docs": 10,
                          "coverage": 0.1, "threshold": 0.3, "per_group": None}}


def _g(gid, n):
    return {"group_id": gid, "kind": "semantic_topic",
            "member_counts": {"core": n, "halo": 0, "micro": 0, "total_docs": n},
            "representatives": [], "prototype": {}}


def _assigned(doc, gid):
    return {"doc_id": doc, "disposition": "assigned",
            "memberships": [{"group_id": gid, "role": "core", "score": 1.0}],
            "reason_code": None}


def _residual(doc, reason="low_local_density"):
    return {"doc_id": doc, "disposition": "residual", "memberships": [],
            "reason_code": reason}


def _root(groups, assignments):
    return _analysis("topics-01", None, {"kind": "all_kept_docs"}, groups, assignments)


def _child(groups, assignments, parent_group="g01", aid="topics-02"):
    return _analysis(aid, "topics-01",
                     {"kind": "parent_group", "analysis_id": "topics-01",
                      "group_id": parent_group}, groups, assignments)


# ---------------- 呈现级派生 ----------------

def test_presentation_replaces_a_subdivided_parent_with_its_children():
    root = _root([_g("g01", 2), _g("g02", 1)],
                 [_assigned("d1", "g01"), _assigned("d2", "g01"),
                  _assigned("d3", "g02"), _residual("d4")])
    child = _child([_g("g01s01", 1)],
                   [_assigned("d1", "g01s01"),
                    _residual("d2", "subdivision_rejected")])
    refs = presentation_groups(_index([root, child]))
    assert ("topics-01", "g01") not in refs        # 父被替换
    assert ("topics-01", "g02") in refs            # 未被细分的保留
    assert ("topics-02", "g01s01") in refs
    assert len(refs) == 2


def test_presentation_is_ordered_by_size_desc():
    root = _root([_g("g01", 1), _g("g02", 3)],
                 [_assigned("d1", "g01"), _assigned("d2", "g02"),
                  _assigned("d3", "g02"), _assigned("d4", "g02")])
    assert presentation_groups(_index([root])) == [
        ("topics-01", "g02"), ("topics-01", "g01")]


def test_effective_residual_covers_docs_stranded_by_subdivision():
    """父簇被细分后，它在 analyses[0] 里的 assigned 已经作废——
    落回子分析 residual 的文档就是真的没有主题。"""
    root = _root([_g("g01", 2)],
                 [_assigned("d1", "g01"), _assigned("d2", "g01"), _residual("d3")])
    child = _child([], [_residual("d1", "under_differentiated_parent"),
                        _residual("d2", "under_differentiated_parent")])
    assert effective_residual_ids(_index([root, child])) == ["d1", "d2", "d3"]


def test_effective_residual_does_not_strand_members_of_surviving_children():
    root = _root([_g("g01", 2)],
                 [_assigned("d1", "g01"), _assigned("d2", "g01"), _residual("d3")])
    child = _child([_g("g01s01", 1)],
                   [_assigned("d1", "g01s01"),
                    _residual("d2", "subdivision_rejected")])
    assert effective_residual_ids(_index([root, child])) == ["d2", "d3"]


def test_effective_residual_without_subdivision_is_just_the_root_residual():
    root = _root([_g("g01", 2)],
                 [_assigned("d1", "g01"), _assigned("d2", "g01"), _residual("d3")])
    assert effective_residual_ids(_index([root])) == ["d3"]


# ---------------- corpus 族 ----------------

def _manifest(**over):
    base = {"counts": {"total": 10, "kept": 6, "dropped_stub": 4,
                       "dropped_duplicate": 0},
            "unresolved_links": [], "documents": []}
    base.update(over)
    return base


def _residual_only_index():
    return _index([_root([], [_residual(f"d{i}") for i in range(6)])])


def test_corpus_insights_skip_conditions_that_do_not_hold():
    kinds = {i.kind for i in build_corpus_insights(_manifest(), _residual_only_index())}
    assert "retention" in kinds
    assert "exact_duplicates" not in kinds     # dropped_duplicate == 0 → 不产出
    assert "broken_refs" not in kinds          # unresolved_links 为空 → 不产出


def test_corpus_insights_emit_conditions_that_do_hold():
    manifest = _manifest(
        counts={"total": 10, "kept": 6, "dropped_stub": 3, "dropped_duplicate": 1},
        unresolved_links=[{"from_doc_id": "d1", "target": "a.png"},
                          {"from_doc_id": "d2", "target": "b.md"}])
    out = {i.kind: i for i in build_corpus_insights(manifest, _residual_only_index())}
    assert "exact_duplicates" in out and "broken_refs" in out
    assert out["broken_refs"].payload["by_kind"] == {"attachment": 1, "document": 1}
    assert "date_blindness" in out             # time_axis.available 为 false


def test_corpus_insights_never_route_to_claude_md():
    got = build_corpus_insights(_manifest(), _residual_only_index())
    assert got, "空列表会让下面的断言恒真"
    assert all(i.claude_md is None for i in got)


def test_corpus_insight_ids_are_unique():
    manifest = _manifest(
        counts={"total": 10, "kept": 6, "dropped_stub": 3, "dropped_duplicate": 1},
        unresolved_links=[{"from_doc_id": "d1", "target": "a.png"}])
    got = build_corpus_insights(manifest, _residual_only_index())
    ids = [i.insight_id for i in got]
    assert len(ids) >= 4
    assert len(set(ids)) == len(ids)
