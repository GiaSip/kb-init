"""在真实语料上的验收测试。语料不在时自动跳过，不阻塞 CI。"""
import os
from pathlib import Path

import pytest

from kb_init.pipeline import run

NOTION = Path(os.path.expanduser("~/Documents/notion-export"))
APPLE = Path(os.path.expanduser("~/Documents/Obsidian Vault/Archive/Apple Notes"))


@pytest.mark.skipif(not NOTION.exists(), reason="Notion 语料不在本机")
def test_notion_export_drops_majority_as_stubs(tmp_path):
    counts = run(NOTION, tmp_path / "out", run_id="acceptance-notion", no_index=True)
    assert counts["total"] > 1500
    stub_ratio = counts["dropped_stub"] / counts["total"]
    assert stub_ratio > 0.45, f"空壳率 {stub_ratio:.0%}，实测基线约 60%"


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_apple_notes_retention_near_baseline(tmp_path):
    counts = run(APPLE, tmp_path / "out", run_id="acceptance-apple", no_index=True)
    assert counts["total"] > 500
    retention = counts["kept"] / counts["total"]
    assert 0.25 < retention < 0.75, f"留存率 {retention:.0%}，历史人工基线 39%"


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_no_unknown_date_explosion(tmp_path):
    """Apple Notes 语料上的粗哨兵：捕获"链条完全崩溃"（100% unknown）的极端情况。

    **本测试不验证降级链的正确性**，那由 test_e2e.py::test_date_resolution_chain_explicit
    的显式断言负责。此处仅作粗哨兵，原因如下：

    Apple Notes 导出对五级降级链中的三级天然无效：
      - frontmatter 级：Apple Notes 导出无 YAML 前置块
      - filename 级：文件名格式如 "新建备忘录.md"，无日期前缀
      - git 级：导出目录不是 git 仓库
    另有 body 级有效性未知，实测 unknown 率约 96%，属预期行为。

    阈值 0.98 的含义：实测 96.1% 通过；若 resolve_date 被删或整体抛异常
    导致所有文档均 unknown（100%），则被此断言捕获。
    哨兵余量约 1.9 个百分点（~12 篇），只能捕获"完全崩溃"，无法捕获
    正则在特定语料上的局部失效——那类问题由 test_e2e 的合成语料测试负责。
    """
    import json
    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-dates", no_index=True)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    assert len(docs) > 0, "语料为空，无法校验"
    unknown = sum(1 for d in docs if d["date_source"] == "unknown")
    assert unknown / len(docs) < 0.98, "降级链五级全落空，说明实现有问题"


@pytest.mark.skipif(not NOTION.exists(), reason="Notion 语料不在本机")
def test_notion_index_time_axis_unavailable(tmp_path):
    """真实导出语料上时间轴必须自动降级——这是条件门的验收。

    用 FakeEmbedder 而非真模型：这条测的是「日期覆盖率低于阈值时时间轴关闭」
    与「coverage 自洽」，与向量质量无关。簇质量的人工验收走 probes/。
    """
    import json

    from tests.fakes import FakeEmbedder

    out = tmp_path / "out"
    counts = run(NOTION, out, run_id="acceptance-index", embedder=FakeEmbedder(dim=16))
    assert counts["index_status"] == "complete"

    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    analysis = index["analyses"][0]
    ta = analysis["time_axis"]
    assert ta["available"] is False, f"日期覆盖率 {ta['coverage']:.1%} 不该触发时间轴"
    assert sum(analysis["coverage"].values()) == counts["kept"]
    assert index["corpus_hash"] == json.loads(
        (out / "manifest.json").read_text(encoding="utf-8")
    )["corpus_hash"]


# ---------------- 2B 洞察层验收 ----------------

def _notion_export_dir():
    if not NOTION.is_dir():
        return None
    for child in sorted(NOTION.iterdir()):
        if child.is_dir() and child.name.startswith("Export-"):
            return child
    return NOTION


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_real_insights_md_round_trips(tmp_path):
    """合成语料测不出真实形态——真实标题里有 emoji、换行、markdown 字符，
    渲染出来必须仍然能被自己的解析器逐条读回去。

    用 FakeEmbedder：这条测的是**格式**在真实文本上的鲁棒性，与向量质量无关。
    """
    import json

    from kb_init.insights_md import parse_markdown, validate_markdown
    from tests.fakes import FakeEmbedder

    out = tmp_path / "out"
    summary = run(APPLE, out, run_id="acceptance-md", embedder=FakeEmbedder(dim=16))
    assert summary["insights_status"] == "complete"

    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    md = (out / "insights.md").read_text(encoding="utf-8")
    validate_markdown(md, payload)
    parsed = parse_markdown(md)
    assert parsed["selections"], "清单为空会让下面的断言恒真"
    assert set(parsed["selections"]) == {i["insight_id"] for i in payload["insights"]}
    assert all(parsed["selections"].values())


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_real_insight_set_is_internally_consistent(tmp_path):
    import json

    from tests.fakes import FakeEmbedder

    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-consistency", embedder=FakeEmbedder(dim=16))
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    assert payload["counts"]["total"] == len(payload["insights"])
    assert payload["corpus_hash"] == manifest["corpus_hash"]
    ids = [i["insight_id"] for i in payload["insights"]]
    assert len(set(ids)) == len(ids)
    # 每条 topic 洞察的证据必须真的属于它那个 group，且非空
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    from kb_init.insights import group_members
    topics = [i for i in payload["insights"] if i["family"] == "topic"]
    for item in topics:
        ref = (item["payload"]["group_ref"]["analysis_id"],
               item["payload"]["group_ref"]["group_id"])
        members = set(group_members(index, ref))
        assert item["payload"]["evidence_doc_ids"], item["insight_id"]
        assert set(item["payload"]["evidence_doc_ids"]) <= members


@pytest.mark.smoke
@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_apple_notes_has_no_flagged_group(tmp_path):
    """选择性验证（负例）：检测器不能把好簇也标记掉。

    Apple Notes 上 5 个簇的内聚度提升量都在 +0.20 附近，远高于 0.12，
    因此不该产生任何子分析——2A′ 在这份语料上是零改动。
    """
    import json

    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-apple-2b")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert len(index["analyses"]) == 1, "Apple Notes 上不应有任何 group 被细分"

    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    assert payload["counts"]["topic"] == 5
    assert 9 <= payload["counts"]["total"] <= 15
    gate = {c["id"]: c for c in payload["revisit_gate"]["conditions"]}
    assert gate["residual_high"]["state"] == "not_evaluable"
    assert gate["insufficient_topics"]["state"] == "not_triggered"


@pytest.mark.smoke
@pytest.mark.skipif(_notion_export_dir() is None, reason="Notion 语料不在本机")
def test_notion_blob_is_subdivided_into_many_topics(tmp_path):
    """正例：那个 509 篇、内聚度只比未分类堆高 0.069 的巨簇必须被细分。"""
    import json

    out = tmp_path / "out"
    run(_notion_export_dir(), out, run_id="acceptance-notion-2b")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert len(index["analyses"]) == 2, "巨簇必须被标记并细分"
    child = index["analyses"][1]
    assert child["input_scope"]["kind"] == "parent_group"
    assert child["method"]["params"]["cluster_selection_method"] == "leaf"

    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    assert payload["counts"]["topic"] >= 8, "细分后主题数应远多于原来的 2 个"
    gate = {c["id"]: c for c in payload["revisit_gate"]["conditions"]}
    assert gate["topics_concentrated"]["state"] == "not_triggered"
    assert gate["insufficient_topics"]["state"] == "not_triggered"
    assert gate["residual_high"]["state"] == "not_evaluable"


@pytest.mark.smoke
@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_real_topic_keywords_are_never_empty(tmp_path):
    """反恒真：只断言「证据 ⊆ 成员」时，关键词全空也能全绿。"""
    import json

    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-apple-kw")
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    topics = [i for i in payload["insights"] if i["family"] == "topic"]
    assert topics
    for item in topics:
        assert item["payload"]["keywords"], item["insight_id"]
        assert len(item["payload"]["evidence_doc_ids"]) == 3
