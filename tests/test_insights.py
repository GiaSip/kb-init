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
                          {"from_doc_id": "d2", "target": "b.md"},
                          {"from_doc_id": "d3", "target": "6"}])
    out = {i.kind: i for i in build_corpus_insights(manifest, _residual_only_index())}
    assert "exact_duplicates" in out and "broken_refs" in out
    # 三桶：无扩展名的目标不能被算成「文档」，否则用户会以为丢了那么多篇笔记
    assert out["broken_refs"].payload["by_kind"] == {
        "attachment": 1, "document": 1, "other": 1}
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


# ---------------- topic / residual 族 ----------------

from kb_init.insights import (
    TOPIC_INSIGHT_CAP,
    build_residual_insights,
    build_topic_insights,
    render,
)


def _corpus_index(n_groups, per_group=5, n_residual=10):
    groups, assignments = [], []
    for g in range(n_groups):
        gid = f"g{g + 1:02d}"
        groups.append(_g(gid, per_group))
        for i in range(per_group):
            assignments.append(_assigned(f"g{g:02d}d{i}", gid))
    for i in range(n_residual):
        assignments.append(_residual(f"r{i:02d}"))
    return _index([_root(groups, assignments)])


def _letters(tag):
    """把 g00 / r03 这类前缀翻成纯字母。

    分词器的拉丁规则要求「字母开头 + 至少两个字母」，`g00alpha` 只会切出
    `alpha`——于是每个簇的词完全相同、lift=1，被正确滤掉。fixture 里混数字
    是在给自己挖坑：看起来像实现坏了，其实是合成语料没有区分度。
    """
    return "".join(chr(ord("a") + int(c)) if c.isdigit() else c for c in tag)


def _bodies_titles(index, long_residual=False):
    bodies, titles = {}, {}
    for a in index["analyses"][0]["assignments"]:
        d = a["doc_id"]
        mark = _letters(d[:3])
        body = (f"{mark}alpha {mark}bravo {mark}charlie {mark}delta "
                f"共同的背景词 ") * 8
        if long_residual and d.startswith("r"):
            body *= 6
        bodies[d] = body
        titles[d] = f"标题-{d}"
    return bodies, titles


def test_topic_insights_carry_keywords_evidence_and_share():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    insights, truncated = build_topic_insights(index, bodies, titles, kept_count=25)
    assert len(insights) == 3
    assert truncated["shown"] == 3 and truncated["total"] == 3
    assert truncated["omitted_group_refs"] == [] and truncated["omitted_docs"] == 0
    for ins in insights:
        assert ins.family == "topic" and ins.kind == "topic_cluster"
        assert ins.payload["keywords"], "关键词为空会让下面的断言恒真"
        assert len(ins.payload["evidence_doc_ids"]) == 3
        assert ins.payload["doc_count"] == 5
        assert 0 < ins.payload["share_of_kept"] < 1
        assert ins.claude_md == {"section": "focus_areas"}


def test_evidence_docs_are_real_members_of_their_group():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    insights, _ = build_topic_insights(index, bodies, titles, kept_count=25)
    assert len(insights) == 3, "topic 全消失时下面的循环恒真"
    from kb_init.insights import group_members
    for ins in insights:
        ref = (ins.payload["group_ref"]["analysis_id"],
               ins.payload["group_ref"]["group_id"])
        members = set(group_members(index, ref))
        assert members
        assert set(ins.payload["evidence_doc_ids"]) <= members


def test_topic_insights_are_capped_with_full_accounting():
    index = _corpus_index(TOPIC_INSIGHT_CAP + 3)
    bodies, titles = _bodies_titles(index)
    insights, truncated = build_topic_insights(index, bodies, titles, kept_count=200)
    assert len(insights) == TOPIC_INSIGHT_CAP
    assert truncated["total"] == TOPIC_INSIGHT_CAP + 3
    assert truncated["shown"] == TOPIC_INSIGHT_CAP
    assert len(truncated["omitted_group_refs"]) == 3
    assert truncated["omitted_docs"] == 15          # 3 组 × 5 篇，必须如实记账


def test_residual_insight_reports_the_share():
    index = _corpus_index(1, per_group=5, n_residual=15)
    bodies, titles = _bodies_titles(index)
    got = {i.kind: i for i in build_residual_insights(index, bodies, titles, 20)}
    assert "fragment_zone" in got
    assert got["fragment_zone"].payload["count"] == 15
    assert got["fragment_zone"].payload["share_of_kept"] == 0.75


def test_long_orphans_lists_the_actual_longest_residual_docs():
    index = _corpus_index(1, per_group=5, n_residual=15)
    bodies, titles = _bodies_titles(index)
    bodies["r07"] = bodies["r07"] * 9            # 让某一篇明确最长
    bodies["r03"] = bodies["r03"] * 5
    got = {i.kind: i for i in build_residual_insights(index, bodies, titles, 20)}
    assert "long_orphans" in got
    p = got["long_orphans"].payload
    assert p["evidence_doc_ids"][:2] == ["r07", "r03"]
    assert p["longest_chars"] == len(bodies["r07"])
    from kb_init.insights import effective_residual_ids
    assert set(p["evidence_doc_ids"]) <= set(effective_residual_ids(index))


def test_long_orphans_absent_when_the_fragment_zone_is_tiny():
    index = _corpus_index(2, per_group=5, n_residual=2)
    bodies, titles = _bodies_titles(index)
    kinds = {i.kind for i in build_residual_insights(index, bodies, titles, 12)}
    assert "fragment_zone" in kinds
    assert "long_orphans" not in kinds


def test_no_residual_insight_when_everything_is_assigned():
    index = _corpus_index(2, per_group=5, n_residual=0)
    bodies, titles = _bodies_titles(index)
    assert build_residual_insights(index, bodies, titles, 10) == []


def test_canonical_text_equals_render_of_payload():
    """双真源的锁：payload 与 canonical_text 必须始终等价。"""
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index, long_residual=True)
    topics, _ = build_topic_insights(index, bodies, titles, 25)
    residual = build_residual_insights(index, bodies, titles, 25)
    assert topics and residual
    for ins in [*topics, *residual]:
        assert ins.canonical_text
        assert render(ins) == ins.canonical_text


def test_topic_text_does_not_claim_to_be_a_topic_name():
    """措辞纪律：关键词不是主题名。写成「你的主题是 X」就是产物在撒谎。"""
    index = _corpus_index(1)
    bodies, titles = _bodies_titles(index)
    topics, _ = build_topic_insights(index, bodies, titles, 15)
    assert "最具区分度的词" in topics[0].canonical_text
    assert "你的主题是" not in topics[0].canonical_text


# ---------------- revisit_gate + 组装 + 写盘 ----------------

import json

import pytest

from kb_init.insights import (
    GATE_RULES_VERSION,
    build_insight_set,
    build_revisit_gate,
    cleanup_insight_files,
    insight_files_remain,
    write_insights,
)


def _std_manifest(**over):
    base = {"counts": {"total": 40, "kept": 25, "dropped_stub": 15,
                       "dropped_duplicate": 0},
            "unresolved_links": [], "documents": []}
    base.update(over)
    return base


def test_gate_defaults_to_unknown_provenance_not_first_party():
    """默认值绝不能是 first_party：那会让每次运行都自称自有语料、把这条
    gate 永久禁用——用一个默认值实现了它本来要防的自证。"""
    gate = build_revisit_gate(10, 10, 0.84)
    states = {c["id"]: c for c in gate["conditions"]}
    assert gate["inputs"]["corpus_provenance"] == "unknown"
    assert states["residual_high"]["state"] == "not_evaluable"
    assert states["residual_high"]["reason"] == "corpus_provenance_unknown"


def test_gate_marks_residual_not_evaluable_on_first_party_corpus():
    gate = build_revisit_gate(topic_count=10, presentation_group_count=10,
                              residual_share=0.84, corpus_provenance="first_party")
    states = {c["id"]: c for c in gate["conditions"]}
    assert states["residual_high"]["state"] == "not_evaluable"
    assert states["residual_high"]["reason"] == "requires_third_party_corpus"
    assert states["residual_high"]["prescription"] == "halo"
    assert gate["rules_version"] == GATE_RULES_VERSION


def test_gate_triggers_on_third_party_corpus_with_high_residual():
    gate = build_revisit_gate(10, 10, 0.84, corpus_provenance="third_party")
    states = {c["id"]: c for c in gate["conditions"]}
    assert states["residual_high"]["state"] == "triggered"


def test_gate_does_not_trigger_residual_when_share_is_low():
    gate = build_revisit_gate(10, 10, 0.32, corpus_provenance="third_party")
    states = {c["id"]: c for c in gate["conditions"]}
    assert states["residual_high"]["state"] == "not_triggered"


def test_gate_topic_conditions_use_topic_count_not_total():
    gate = build_revisit_gate(topic_count=2, presentation_group_count=2,
                              residual_share=0.1, corpus_provenance="third_party")
    states = {c["id"]: c for c in gate["conditions"]}
    assert states["insufficient_topics"]["state"] == "triggered"
    assert states["topics_concentrated"]["state"] == "triggered"
    assert states["insufficient_topics"]["prescription"] == "subdivide"


def test_counts_are_derived_from_the_insight_array():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    payload = build_insight_set(index, _std_manifest(), bodies, titles)
    families = [i["family"] for i in payload["insights"]]
    assert payload["counts"]["total"] == len(payload["insights"])
    assert payload["counts"]["topic"] == families.count("topic") == 3
    assert payload["counts"]["corpus"] == families.count("corpus")
    assert payload["counts"]["residual"] == families.count("residual")


def test_insight_ids_are_unique_and_bound_to_the_index_run():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    payload = build_insight_set(index, _std_manifest(), bodies, titles)
    ids = [i["insight_id"] for i in payload["insights"]]
    assert len(set(ids)) == len(ids)
    assert payload["run_id"] == index["run_id"]
    assert payload["corpus_hash"] == index["corpus_hash"]


def test_naming_params_are_recorded_in_the_artifact():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    payload = build_insight_set(index, _std_manifest(), bodies, titles)
    params = payload["naming"]["params"]
    for key in ("min_lift", "min_cluster_df", "cjk_min_boundary_entropy", "stoplist"):
        assert key in params


def test_render_is_the_sole_generator_for_every_family():
    """双真源的锁必须覆盖**全部三族**。原先只查了 topic/residual，
    corpus 族手写 canonical_text 的漂移就漏过去了（Codex 终审第 4 条）。"""
    from kb_init.insights import Insight, render

    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index, long_residual=True)
    payload = build_insight_set(index, _std_manifest(
        counts={"total": 40, "kept": 25, "dropped_stub": 14, "dropped_duplicate": 1},
        unresolved_links=[{"from_doc_id": "x", "target": "a.png"}]), bodies, titles)
    families = {i["family"] for i in payload["insights"]}
    assert families == {"topic", "residual", "corpus"}, families
    for item in payload["insights"]:
        assert item["canonical_text"]
        assert render(Insight(**item)) == item["canonical_text"], item["insight_id"]


def test_groups_without_keywords_are_not_emitted_but_are_accounted_for():
    """占位洞察会计进 topic 数、把 revisit gate 顶过阈值——那是第四条兜底路径。
    不产出，但必须记账，不能静默消失。"""
    index = _corpus_index(2)
    bodies, titles = _bodies_titles(index)
    # 让所有文档正文完全一样 → 没有任何词有区分度
    same = "完全一样的正文 identical body text " * 8
    bodies = {d: same for d in bodies}
    insights, truncated = build_topic_insights(index, bodies, titles, kept_count=20)
    assert insights == []
    assert len(truncated["unnamed_group_refs"]) == 2
    assert truncated["unnamed_docs"] == 10
    assert truncated["shown"] == 0


def test_is_byte_identical_across_runs():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    a = json.dumps(build_insight_set(index, _std_manifest(), bodies, titles),
                   ensure_ascii=False)
    b = json.dumps(build_insight_set(index, _std_manifest(), bodies, titles),
                   ensure_ascii=False)
    assert a == b


def test_write_is_a_sub_transaction(tmp_path, monkeypatch):
    from pathlib import Path

    real = Path.write_text

    def explode(self, *a, **k):
        if self.name == "insights.md":
            raise OSError("写 md 失败")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", explode)
    with pytest.raises(OSError):
        write_insights(tmp_path, {"insights": []}, "# md")
    monkeypatch.undo()
    assert not insight_files_remain(tmp_path)


def test_write_then_cleanup_leaves_nothing(tmp_path):
    write_insights(tmp_path, {"insights": []}, "# md")
    assert insight_files_remain(tmp_path)
    cleanup_insight_files(tmp_path)
    assert not insight_files_remain(tmp_path)


def test_length_profile_reports_the_distribution_without_a_magic_threshold():
    bodies = {f"d{i}": "x" * (100 * (i + 1)) for i in range(5)}
    got = {i.kind: i for i in
           build_corpus_insights(_manifest(), _residual_only_index(), bodies)}
    assert "length_profile" in got
    p = got["length_profile"].payload
    assert p["count"] == 5
    assert p["shortest_chars"] == 100 and p["longest_chars"] == 500
    assert p["median_chars"] == 300


def test_length_profile_absent_when_there_are_no_bodies():
    kinds = {i.kind for i in build_corpus_insights(_manifest(), _residual_only_index())}
    assert "length_profile" not in kinds


def test_unknown_provenance_value_is_rejected():
    """拼错的值会落进「非 third_party」分支被当成自有语料，同时原样写进 inputs
    ——产物于是自相矛盾：它声称的来源不是判定用的那个。"""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="corpus_provenance"):
        build_revisit_gate(5, 5, 0.5, corpus_provenance="thirdparty")


def test_length_profile_median_is_correct_for_even_samples():
    """偶数样本取上中位数会把 [100, 200] 报成 200。"""
    bodies = {"a": "x" * 100, "b": "x" * 200}
    got = {i.kind: i for i in
           build_corpus_insights(_manifest(), _residual_only_index(), bodies)}
    assert got["length_profile"].payload["median_chars"] == 150


def test_r1_routes_to_coverage_section():
    """碎片区洞察进档案线：档案只讲了 kept 的一小部分，不说这条，
    agent 会把它当成全集（2D spec §2.3）。"""
    index = _corpus_index(1, per_group=5, n_residual=15)
    bodies, titles = _bodies_titles(index)
    got = {i.kind: i for i in build_residual_insights(index, bodies, titles, 20)}
    assert got["fragment_zone"].claude_md == {"section": "coverage"}


def test_r2_stays_out_of_archive():
    """负例：防止「把 residual 整族路由过去」的实现蒙混过关。
    「篇幅最大的 3 篇」是给人看的线索，对 agent 的自我认知没有用。"""
    index = _corpus_index(1, per_group=5, n_residual=15)
    bodies, titles = _bodies_titles(index)
    got = {i.kind: i for i in build_residual_insights(index, bodies, titles, 20)}
    assert "long_orphans" in got, "空的话下面这条断言恒真"
    assert got["long_orphans"].claude_md is None
