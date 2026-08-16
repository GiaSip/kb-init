"""档案线（`kb-init compile` → 用户知识库的 CLAUDE.md）。

⚠️ 这里的 CLAUDE.md 指**用户知识库的**那份，不是本仓库根目录那份。
"""
import pytest

from kb_init.claude_md import (
    ArchiveContractError,
    ArchiveEmptyError,
    KNOWN_SECTIONS,
    SECTIONS,
    check_structure,
    render_archive,
    select_for_archive,
    verify_canonical_texts,
)

REQUIRED_KEYS = ("insight_id", "family", "kind", "payload",
                 "canonical_text", "claude_md")


def _insight(iid, section="focus_areas", **over):
    """fixture 纪律：默认样本刻意不规整——多语言关键词、带换行与多余空白的
    证据标题。太规整的合成数据会把好实现判成坏的（2B 踩过）。"""
    item = {
        "insight_id": iid,
        "family": "topic",
        "kind": "topic_cluster",
        "payload": {
            "keywords": ["排版", "typography", "griglia"],
            "doc_count": 7,
            "share_of_kept": 0.031,
            "evidence_doc_ids": ["d1", "d2"],
            "evidence_titles": ["带  多余   空格的标题", "跨\n行\n的标题"],
        },
        "canonical_text": f"{iid} 的正文",
        "evidence": {"doc_ids": ["d1", "d2"], "stat": None},
        "claude_md": None if section is None else {"section": section},
    }
    item.update(over)
    return item


def _payload(*insights, **top):
    out = {
        "schema_version": "0.1",
        "run_id": "r1",
        "corpus_hash": "c1",
        "insights": list(insights) or [_insight("T1")],
    }
    out.update(top)
    return out


# ---------------- SECTIONS 表 ----------------

def test_sections_table_is_ordered_and_consistent_with_known_set():
    assert [s[0] for s in SECTIONS] == ["focus_areas", "coverage"]
    assert KNOWN_SECTIONS == {s[0] for s in SECTIONS}


def test_leads_state_only_pipeline_facts():
    """静态常量也会撒谎：导语一旦陈述「这份语料的」事实，换份语料即成假话。
    所以导语里不许出现任何与语料有关的词（Codex 审 #7）。"""
    forbidden = ("这份语料", "时间", "稳定性", "篇数太少", "日期")
    for _, _, lead in SECTIONS:
        if lead is None:
            continue
        assert not any(w in lead for w in forbidden[1:]), lead
        assert forbidden[0] not in lead, lead


# ---------------- 结构 gate ----------------

def test_check_structure_accepts_valid_payload():
    """负例组的配对正例。缺了它，一个恒抛错的 check_structure 也能全绿。"""
    check_structure(_payload(_insight("T1"), _insight("R1", section="coverage"),
                             _insight("C1", section=None)))


def test_duplicate_insight_id_fails_closed():
    """一个勾选框授权两段正文进档案（Codex 审 #5）。"""
    with pytest.raises(ArchiveContractError, match="T1"):
        check_structure(_payload(_insight("T1"), _insight("T1")))


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_missing_required_key_fails_closed(key):
    item = _insight("T1")
    del item[key]
    with pytest.raises(ArchiveContractError):
        check_structure(_payload(item))


@pytest.mark.parametrize("claude_md", [
    {},                                            # 有 dict 没 section
    {"section": None},
    {"section": ""},
    {"section": 7},
    {"section": ["focus_areas"]},
    {"section": "focus_areas", "extra": 1},        # 多余键：形状对不上就是对不上
    "focus_areas",                                 # 根本不是 dict
])
def test_malformed_claude_md_shapes_fail_closed(claude_md):
    with pytest.raises(ArchiveContractError):
        check_structure(_payload(_insight("T1", claude_md=claude_md)))


def test_unknown_section_fails_closed():
    with pytest.raises(ArchiveContractError, match="blind_spots"):
        check_structure(_payload(_insight("T1", section="blind_spots")))


def test_unknown_section_fails_even_when_unchecked():
    """核心守卫（2D spec §5.1）：结构 gate 根本不看勾选状态。

    若它晚于「按勾选过滤」，2E 新增的一节只要用户没勾就永远不报错；
    更糟的是当它恰好是唯一能进档案的一族时，管道会走到「没有可归档条目」
    而报出退出码 8——用一个错误码把用户支去改一份没有问题的清单。
    """
    payload = _payload(_insight("T1", section="blind_spots"))
    assert check_structure.__code__.co_argcount == 1, (
        "check_structure 不该接收 selections——接收了就迟早会去看它")
    with pytest.raises(ArchiveContractError):
        check_structure(payload)


def test_insights_must_be_a_list():
    with pytest.raises(ArchiveContractError):
        check_structure({"schema_version": "0.1", "run_id": "r1",
                         "corpus_hash": "c1", "insights": {"T1": {}}})


# ---------------- 选择（过滤 + 分节） ----------------

def _all_checked(payload):
    return {i["insight_id"]: True for i in payload["insights"]}


def test_unchecked_items_are_excluded():
    payload = _payload(_insight("T1"), _insight("T2"))
    grouped = select_for_archive(payload, {"T1": True, "T2": False})
    assert [i["insight_id"] for _, items in grouped for i in items] == ["T1"]


def test_null_claude_md_never_enters_archive():
    """corpus 族勾着也不进：留存率、断链数对 agent 无用。"""
    payload = _payload(_insight("T1"), _insight("C1", section=None))
    grouped = select_for_archive(payload, _all_checked(payload))
    assert [i["insight_id"] for _, items in grouped for i in items] == ["T1"]


def test_section_and_item_order_follows_json():
    """节序按 SECTIONS，节内序按数组序。

    构造时故意把 coverage 放在数组最前、T2 放在 T1 之前——否则「顺序对」
    这条断言在一个原样返回的实现上也永远成立。
    """
    payload = _payload(_insight("R1", section="coverage"),
                       _insight("T2"), _insight("T1"))
    grouped = select_for_archive(payload, _all_checked(payload))
    assert [s for s, _ in grouped] == ["focus_areas", "coverage"]
    assert [i["insight_id"] for i in grouped[0][1]] == ["T2", "T1"]


def test_empty_sections_do_not_appear():
    payload = _payload(_insight("T1"))
    assert [s for s, _ in select_for_archive(payload, _all_checked(payload))] \
        == ["focus_areas"]


def test_empty_selection_raises_empty():
    payload = _payload(_insight("T1"), _insight("T2"))
    with pytest.raises(ArchiveEmptyError):
        select_for_archive(payload, {"T1": False, "T2": False})


def test_only_null_routed_insights_raises_empty():
    """全是 corpus 族且全勾着 → 依然是「没有条目能进档案」，不是「用户没勾」。"""
    payload = _payload(_insight("C1", section=None), _insight("C2", section=None))
    with pytest.raises(ArchiveEmptyError):
        select_for_archive(payload, _all_checked(payload))


# ---------------- canonical_text 校验 ----------------

def _real_insight(**over):
    """用真渲染器造一条 canonical_text 名副其实的洞察。"""
    from kb_init.insights import Insight, render

    payload = {"count": 15, "share_of_kept": 0.75}
    text = render(Insight("R1", "residual", "fragment_zone", payload, ""))
    item = {"insight_id": "R1", "family": "residual", "kind": "fragment_zone",
            "payload": payload, "canonical_text": text,
            "evidence": {"doc_ids": [], "stat": None},
            "claude_md": {"section": "coverage"}}
    item.update(over)
    return item


def test_verify_canonical_passes_on_untampered():
    payload = _payload(_real_insight())
    verify_canonical_texts(select_for_archive(payload, _all_checked(payload)))


def test_verify_canonical_detects_tampering():
    payload = _payload(_real_insight(canonical_text="我自己改的一句话"))
    grouped = select_for_archive(payload, _all_checked(payload))
    with pytest.raises(ArchiveContractError, match="R1"):
        verify_canonical_texts(grouped)


def test_verify_canonical_ignores_unarchived():
    """只校验进档案的那几条。未进档案的条目文案变了不该挡住用户。"""
    tampered = _real_insight(insight_id="C1", claude_md=None,
                             canonical_text="对不上的文案")
    payload = _payload(_real_insight(), tampered)
    verify_canonical_texts(select_for_archive(payload, _all_checked(payload)))


def test_verify_canonical_rejects_unknown_kind():
    """kind 是本版渲染器没有的 → 同样是「json 与本版对不上」，不是崩溃。"""
    payload = _payload(_real_insight(kind="future_kind"))
    grouped = select_for_archive(payload, _all_checked(payload))
    with pytest.raises(ArchiveContractError):
        verify_canonical_texts(grouped)


# ---------------- 渲染 ----------------

def _render_all(payload):
    return render_archive(payload, select_for_archive(payload, _all_checked(payload)))


def test_body_is_canonical_text_verbatim():
    """逐字。2D 若自己排一句更好看的，2D 的渲染器升级会犯和 2B 一模一样的病。"""
    payload = _payload(_insight("T1", canonical_text="这 29 篇里最具区分度的词是 甲 · 乙"))
    assert "- 这 29 篇里最具区分度的词是 甲 · 乙" in _render_all(payload).splitlines()


def test_evidence_line_folds_whitespace_only():
    item = _insight("T1")
    item["payload"]["evidence_titles"] = ["带  多余   空格", "跨\n行"]
    line = [ln for ln in _render_all(_payload(item)).splitlines()
            if "证据" in ln][0]
    assert "带 多余 空格" in line and "跨 行" in line


def test_empty_evidence_titles_emits_no_evidence_line():
    item = _insight("T1")
    item["payload"]["evidence_titles"] = []
    assert "证据" not in _render_all(_payload(item))


def test_missing_evidence_titles_key_is_fine():
    item = _insight("T1")
    del item["payload"]["evidence_titles"]
    assert "证据" not in _render_all(_payload(item))


def test_lead_is_static_and_corpus_independent():
    """同一节的导语在两份差异很大的语料上必须逐字相同（Codex 审 #7）。"""
    a = _payload(_insight("T1"), run_id="ra", corpus_hash="ca")
    b = _payload(_insight("T1", canonical_text="完全不同的一句"),
                 run_id="rb", corpus_hash="cb")
    lead = [ln for ln in _render_all(a).splitlines() if ln.startswith(">")]
    assert lead and lead == [ln for ln in _render_all(b).splitlines()
                             if ln.startswith(">")]


def test_header_carries_identity():
    out = _render_all(_payload(_insight("T1")))
    assert "<!-- kb-init:claude_md run_id=r1 corpus_hash=c1 schema_version=0.1 -->" in out


def test_headings_come_from_sections_table():
    payload = _payload(_insight("T1"), _insight("R1", section="coverage"))
    out = _render_all(payload)
    assert "## 关注领域" in out and "## 这份档案的覆盖范围" in out
    assert out.index("## 关注领域") < out.index("## 这份档案的覆盖范围")


def test_archive_ends_with_single_newline():
    assert _render_all(_payload(_insight("T1"))).endswith("\n")
