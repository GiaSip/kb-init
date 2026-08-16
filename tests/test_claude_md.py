"""档案线（`kb-init compile` → 用户知识库的 CLAUDE.md）。

⚠️ 这里的 CLAUDE.md 指**用户知识库的**那份，不是本仓库根目录那份。
"""
import pytest

from kb_init.claude_md import (
    ArchiveContractError,
    KNOWN_SECTIONS,
    SECTIONS,
    check_structure,
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
