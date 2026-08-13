import json
from pathlib import Path

from kb_init.pipeline import run


def _corpus(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "good1.md").write_text(
        "---\ntitle: 好文章\ncreated: 2023-04-01\n---\n\n" + "内容" * 200,
        encoding="utf-8",
    )
    (root / "good2.md").write_text("# 另一篇\n\n" + "别的内容" * 200, encoding="utf-8")
    (root / "stub.md").write_text("短", encoding="utf-8")
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "dup.md").write_text(
        "---\ntitle: 好文章\ncreated: 2023-04-01\n---\n\n" + "内容" * 200,
        encoding="utf-8",
    )
    return root


def test_end_to_end_counts(tmp_path):
    src = _corpus(tmp_path / "src")
    counts = run(src, tmp_path / "out", run_id="r1")
    assert counts["total"] == 4
    assert counts["kept"] == 2
    assert counts["dropped_stub"] == 1
    assert counts["dropped_duplicate"] == 1


def test_end_to_end_writes_only_kept_files(tmp_path):
    src = _corpus(tmp_path / "src")
    run(src, tmp_path / "out", run_id="r1")
    assert len(list((tmp_path / "out" / "knowledge").glob("*.md"))) == 2


def test_every_kept_doc_has_resolvable_out_path(tmp_path):
    """守卫测试：证据链接必须全部可解析——这是原设计顺序 bug 的回归测试。"""
    src = _corpus(tmp_path / "src")
    out = tmp_path / "out"
    run(src, out, run_id="r1")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    kept = [d for d in manifest["documents"] if d["status"] == "kept"]
    assert kept
    for entry in kept:
        assert entry["out_relpath"] is not None
        assert (out / entry["out_relpath"]).exists()


def test_dropped_docs_are_still_in_manifest(tmp_path):
    src = _corpus(tmp_path / "src")
    out = tmp_path / "out"
    run(src, out, run_id="r1")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["documents"]) == 4


def test_rerun_same_corpus_yields_same_corpus_hash(tmp_path):
    src = _corpus(tmp_path / "src")
    run(src, tmp_path / "out1", run_id="r1")
    run(src, tmp_path / "out2", run_id="r2")
    h1 = json.loads((tmp_path / "out1" / "manifest.json").read_text())["corpus_hash"]
    h2 = json.loads((tmp_path / "out2" / "manifest.json").read_text())["corpus_hash"]
    assert h1 == h2


def test_date_resolution_chain_explicit(tmp_path):
    """显式验证降级链：frontmatter 日期正确提取，无元数据时按序降级到 unknown。

    这才是链条正确性的真正验证——Apple Notes 语料有 3/5 级天然无效，
    无法区分"链条实现正确"与"链条实现完全错误"，所以链条测试在这里做。
    """
    src = _corpus(tmp_path / "src")
    out = tmp_path / "out"
    run(src, out, run_id="r1")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    by_relpath = {d["source_relpath"]: d for d in manifest["documents"]}

    # good1.md 与 a/b/c/dup.md 均含 frontmatter `created: 2023-04-01`。
    # walk_source 排序后 a/b/c/dup.md 先处理（被标 kept），good1.md 被标 duplicate，
    # 但 date 字段由 resolve_date 独立设置，与 clean 状态无关——两者均应命中 frontmatter 级。
    for relpath in ("good1.md", "a/b/c/dup.md"):
        doc = by_relpath[relpath]
        assert doc["date_source"] == "frontmatter", (
            f"{relpath}: expected frontmatter, got {doc['date_source']!r}"
        )
        assert doc["created"] == "2023-04-01", (
            f"{relpath}: expected 2023-04-01, got {doc['created']!r}"
        )

    # good2.md：无 frontmatter、正文无日期串、文件名无日期前缀、tmp_path 非 git 仓库。
    # 五级全空 → 应落 unknown，确认链条在无元数据时确实走到底而非停在某级。
    good2 = by_relpath["good2.md"]
    assert good2["date_source"] == "unknown", (
        f"good2.md: expected unknown, got {good2['date_source']!r}"
    )
