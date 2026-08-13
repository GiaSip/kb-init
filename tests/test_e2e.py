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
