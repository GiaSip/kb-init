"""在真实语料上的验收测试。语料不在时自动跳过，不阻塞 CI。"""
import os
from pathlib import Path

import pytest

from kb_init.pipeline import run

NOTION = Path(os.path.expanduser("~/Documents/notion-export"))
APPLE = Path(os.path.expanduser("~/Documents/Obsidian Vault/Archive/Apple Notes"))


@pytest.mark.skipif(not NOTION.exists(), reason="Notion 语料不在本机")
def test_notion_export_drops_majority_as_stubs(tmp_path):
    counts = run(NOTION, tmp_path / "out", run_id="acceptance-notion")
    assert counts["total"] > 1500
    stub_ratio = counts["dropped_stub"] / counts["total"]
    assert stub_ratio > 0.45, f"空壳率 {stub_ratio:.0%}，实测基线约 60%"


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_apple_notes_retention_near_baseline(tmp_path):
    counts = run(APPLE, tmp_path / "out", run_id="acceptance-apple")
    assert counts["total"] > 500
    retention = counts["kept"] / counts["total"]
    assert 0.25 < retention < 0.75, f"留存率 {retention:.0%}，历史人工基线 39%"


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_no_unknown_date_explosion(tmp_path):
    """降级链若整体失效，unknown 会爆表——这是链条坏掉的哨兵。"""
    import json
    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-dates")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    unknown = sum(1 for d in docs if d["date_source"] == "unknown")
    # Apple Notes 导出本身无日期元数据，实测 unknown 率约 96%。
    # 阈值 0.98 的含义：仅在"五级链条全部失效、所有文档都落 unknown"时触发——
    # 实测 96.1% 低于 0.98；若链条完全断掉则会到 100%，会被此断言捕获。
    assert unknown / len(docs) < 0.98, "降级链五级全落空，说明实现有问题"
