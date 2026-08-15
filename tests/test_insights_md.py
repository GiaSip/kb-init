import pytest

from kb_init.insights_md import (
    InsightsValidationError,
    parse_markdown,
    render_markdown,
    validate_markdown,
)


def _payload(**over):
    base = {
        "schema_version": "0.1", "run_id": "run-1", "corpus_hash": "hash-1",
        "counts": {"topic": 2, "residual": 1, "corpus": 1, "total": 4},
        "presentation": {"group_refs": [],
                         "truncated": {"shown": 2, "total": 2,
                                       "omitted_group_refs": [], "omitted_docs": 0}},
        "insights": [
            {"insight_id": "T1", "family": "topic", "kind": "topic_cluster",
             "canonical_text": "这 9 篇里最具区分度的词是 a · b — 占 kept 3.0%",
             "payload": {"evidence_titles": ["标题一", "标题二", "标题三"]},
             "evidence": {"doc_ids": ["d1", "d2", "d3"], "stat": None},
             "claude_md": {"section": "focus_areas"}},
            {"insight_id": "T2", "family": "topic", "kind": "topic_cluster",
             "canonical_text": "这 5 篇里最具区分度的词是 c · d — 占 kept 1.7%",
             "payload": {"evidence_titles": ["甲", "乙"]},
             "evidence": {"doc_ids": ["d4"], "stat": None},
             "claude_md": {"section": "focus_areas"}},
            {"insight_id": "R1", "family": "residual", "kind": "fragment_zone",
             "canonical_text": "222 篇没有形成主题（占 kept 77.4%）",
             "payload": {}, "evidence": {"doc_ids": [], "stat": None},
             "claude_md": None},
            {"insight_id": "C1", "family": "corpus", "kind": "retention",
             "canonical_text": "读入 620 篇，留下 287 篇（46.3%）；333 篇是空壳",
             "payload": {}, "evidence": {"doc_ids": [], "stat": None},
             "claude_md": None},
        ],
    }
    base.update(over)
    return base


def test_round_trip_preserves_ids_and_all_checked_by_default():
    parsed = parse_markdown(render_markdown(_payload()))
    assert parsed["run_id"] == "run-1"
    assert parsed["corpus_hash"] == "hash-1"
    assert parsed["selections"] == {"T1": True, "T2": True, "R1": True, "C1": True}


def test_unchecking_is_the_only_edit_that_survives():
    md = render_markdown(_payload()).replace("- [x] `T2`", "- [ ] `T2`")
    md = md.replace("222 篇没有形成主题", "用户瞎改的文案")
    parsed = parse_markdown(md)
    assert parsed["selections"]["T2"] is False
    assert parsed["selections"]["R1"] is True     # 改正文不影响解析
    validate_markdown(md, _payload())             # 改正文也不该判失败


def test_missing_id_fails_closed():
    md = "\n".join(line for line in render_markdown(_payload()).splitlines()
                   if "`C1`" not in line)
    with pytest.raises(InsightsValidationError, match="C1"):
        validate_markdown(md, _payload())


def test_duplicate_id_fails_closed_with_line_number():
    lines = render_markdown(_payload()).splitlines()
    idx = next(i for i, line in enumerate(lines) if "`T1`" in line)
    lines.insert(idx + 1, lines[idx])
    with pytest.raises(InsightsValidationError, match=r"第 \d+ 行.*T1"):
        validate_markdown("\n".join(lines), _payload())


def test_unknown_id_fails_closed_with_line_number():
    md = render_markdown(_payload()) + "\n- [x] `T9` 不知道哪来的\n"
    with pytest.raises(InsightsValidationError, match=r"第 \d+ 行.*T9"):
        validate_markdown(md, _payload())


def test_cross_run_fails_closed():
    md = render_markdown(_payload())
    with pytest.raises(InsightsValidationError, match="run_id"):
        validate_markdown(md, _payload(run_id="run-2"))


def test_cross_corpus_fails_closed():
    md = render_markdown(_payload())
    with pytest.raises(InsightsValidationError, match="corpus_hash"):
        validate_markdown(md, _payload(corpus_hash="hash-2"))


def test_broken_header_fails_closed():
    md = render_markdown(_payload()).replace("kb-init:run_id=", "kb-init:runid=")
    with pytest.raises(InsightsValidationError, match="头部"):
        validate_markdown(md, _payload())


def test_ids_are_visible_in_the_rendered_text():
    md = render_markdown(_payload())
    for insight_id in ("T1", "T2", "R1", "C1"):
        assert f"`{insight_id}`" in md


def test_sections_are_grouped_by_family_with_counts():
    md = render_markdown(_payload())
    assert "## 主题（2 条）" in md
    assert "## 碎片区（1 条）" in md
    assert "## 语料（1 条）" in md


def test_truncation_is_disclosed_in_the_checklist():
    payload = _payload(presentation={"group_refs": [],
                                     "truncated": {"shown": 12, "total": 15,
                                                   "omitted_group_refs": [],
                                                   "omitted_docs": 41}})
    md = render_markdown(payload)
    assert "前 12" in md and "共 15" in md and "41 篇" in md


def test_multiline_titles_do_not_break_the_line_format():
    """真实标题里有换行——渲染后必须仍然一条洞察占一行，否则解析器会漏读。"""
    payload = _payload()
    payload["insights"][0]["payload"]["evidence_titles"] = ["带\n换行的\n标题", "正常"]
    md = render_markdown(payload)
    validate_markdown(md, payload)
    assert parse_markdown(md)["selections"]["T1"] is True


def test_empty_insight_set_renders_a_valid_header_only_document():
    empty = _payload(insights=[],
                     counts={"topic": 0, "residual": 0, "corpus": 0, "total": 0})
    md = render_markdown(empty)
    assert parse_markdown(md)["selections"] == {}
    validate_markdown(md, empty)
