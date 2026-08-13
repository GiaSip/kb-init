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
    # filename 级正向证据：无 frontmatter、正文无日期串 → 降级链走到 filename 级命中
    (root / "2020-06-15-good3.md").write_text(
        "内容" * 110,  # 220 字符，无 YYYY-MM-DD 格式串
        encoding="utf-8",
    )
    # body 级正向证据：无 frontmatter、文件名无日期、正文含日期 → 降级链走到 body 级命中
    (root / "good4.md").write_text(
        "创建于 2019-03-22\n\n" + "内容" * 110,  # body 含日期，文件名无日期
        encoding="utf-8",
    )
    return root


def test_end_to_end_counts(tmp_path):
    src = _corpus(tmp_path / "src")
    counts = run(src, tmp_path / "out", run_id="r1")
    assert counts["total"] == 6
    assert counts["kept"] == 4
    assert counts["dropped_stub"] == 1
    assert counts["dropped_duplicate"] == 1


def test_end_to_end_writes_only_kept_files(tmp_path):
    src = _corpus(tmp_path / "src")
    run(src, tmp_path / "out", run_id="r1")
    assert len(list((tmp_path / "out" / "knowledge").glob("*.md"))) == 4


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
    assert len(manifest["documents"]) == 6


def test_rerun_same_corpus_yields_same_corpus_hash(tmp_path):
    src = _corpus(tmp_path / "src")
    run(src, tmp_path / "out1", run_id="r1")
    run(src, tmp_path / "out2", run_id="r2")
    h1 = json.loads((tmp_path / "out1" / "manifest.json").read_text())["corpus_hash"]
    h2 = json.loads((tmp_path / "out2" / "manifest.json").read_text())["corpus_hash"]
    assert h1 == h2


def test_date_resolution_chain_explicit(tmp_path):
    """显式验证降级链各级：有正向命中证据的三级 + 全空落 unknown 的一个文件。

    Apple Notes 语料有 3/5 级天然无效（frontmatter/filename/git），无法区分
    链条实现正确与实现错误，因此链条正确性验证全部在合成语料中完成。

    覆盖级别：
    - frontmatter 级：good1.md / a/b/c/dup.md（显式 YAML created 字段）
    - body 级：good4.md（无 frontmatter，正文含日期串）
    - filename 级：2020-06-15-good3.md（无 frontmatter，正文无日期）
    - unknown 级：good2.md（无任何日期元数据，tmp_path 非 git 仓库）
    """
    src = _corpus(tmp_path / "src")
    out = tmp_path / "out"
    run(src, out, run_id="r1")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    by_relpath = {d["source_relpath"]: d for d in manifest["documents"]}

    # frontmatter 级：good1.md 与 a/b/c/dup.md 均含 `created: 2023-04-01`。
    # walk_source 排序后 a/b/c/dup.md 先处理（marked kept），good1.md 被标 duplicate，
    # 但 date 字段由 resolve_date 独立设置，与 clean 状态无关——两者均应命中 frontmatter。
    for relpath in ("good1.md", "a/b/c/dup.md"):
        doc = by_relpath[relpath]
        assert doc["date_source"] == "frontmatter", (
            f"{relpath}: expected frontmatter, got {doc['date_source']!r}"
        )
        assert doc["created"] == "2023-04-01", (
            f"{relpath}: expected 2023-04-01, got {doc['created']!r}"
        )

    # body 级：good4.md 无 frontmatter、文件名无日期、正文含 "2019-03-22"。
    # 链条跳过 frontmatter 级 → 正文搜索命中 → date_source == "body"。
    # 这证明 frontmatter 缺失时链条确实走到了 body 级而不是直接掉到 unknown。
    good4 = by_relpath["good4.md"]
    assert good4["date_source"] == "body", (
        f"good4.md: expected body, got {good4['date_source']!r}"
    )
    assert good4["created"] == "2019-03-22", (
        f"good4.md: expected 2019-03-22, got {good4['created']!r}"
    )

    # filename 级：2020-06-15-good3.md 无 frontmatter、正文无日期串、文件名含日期。
    # 链条跳过 frontmatter 和 body 级 → filename 搜索命中 → date_source == "filename"。
    # 这证明 body 级未命中时链条确实走到了 filename 级而不是直接掉到 unknown。
    good3 = by_relpath["2020-06-15-good3.md"]
    assert good3["date_source"] == "filename", (
        f"2020-06-15-good3.md: expected filename, got {good3['date_source']!r}"
    )
    assert good3["created"] == "2020-06-15", (
        f"2020-06-15-good3.md: expected 2020-06-15, got {good3['created']!r}"
    )

    # unknown 级：good2.md 无 frontmatter、正文无日期串、文件名无日期、tmp_path 非 git 仓库。
    # 五级全空 → 落 unknown，确认链条走到底而非在中途停止。
    good2 = by_relpath["good2.md"]
    assert good2["date_source"] == "unknown", (
        f"good2.md: expected unknown, got {good2['date_source']!r}"
    )
