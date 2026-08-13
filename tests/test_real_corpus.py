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
    run(APPLE, out, run_id="acceptance-dates")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    assert len(docs) > 0, "语料为空，无法校验"
    unknown = sum(1 for d in docs if d["date_source"] == "unknown")
    assert unknown / len(docs) < 0.98, "降级链五级全落空，说明实现有问题"
