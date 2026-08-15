import json

import pytest

from kb_init.cli import main
from kb_init.pipeline import run
from tests.fakes import FakeEmbedder

LONG = "内容" * 110


def _corpus(root, n=14):
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / f"doc{i:02d}.md").write_text(
            f"# 标题{i}\n\n{LONG}第{i}篇", encoding="utf-8"
        )


def test_index_is_written_and_bound_to_manifest(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    counts = run(src, out, run_id="idx", embedder=FakeEmbedder(dim=8))

    assert counts["index_status"] == "complete"
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert index["corpus_hash"] == manifest["corpus_hash"]
    assert index["run_id"] == manifest["run_id"]
    assert manifest["index_status"] == "complete"
    assert (out / "index-vectors.npy").exists()

    kept = [d["doc_id"] for d in manifest["documents"] if d["status"] == "kept"]
    assigned = [a["doc_id"] for a in index["analyses"][0]["assignments"]]
    assert sorted(assigned) == sorted(kept)


def test_vector_rows_match_document_count(tmp_path):
    import numpy as np

    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    counts = run(src, out, run_id="idx-vec", embedder=FakeEmbedder(dim=8))
    matrix = np.load(out / "index-vectors.npy")
    assert matrix.shape[0] == counts["kept"]
    assert matrix.dtype == np.float32


def test_time_axis_is_unavailable_when_dates_are_missing(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    run(src, out, run_id="idx2", embedder=FakeEmbedder(dim=8))
    ta = json.loads((out / "index.json").read_text(encoding="utf-8"))["analyses"][0]["time_axis"]
    assert ta["available"] is False
    assert ta["total_docs"] == 14


def test_no_index_publishes_cleaned_output_without_index(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    counts = run(src, out, run_id="idx3", no_index=True)

    assert counts["index_status"] == "skipped"
    assert (out / "knowledge").is_dir()
    assert not (out / "index.json").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["index_status"] == "skipped"


def test_index_failure_still_publishes_cleaned_output(tmp_path):
    """本任务的核心：索引炸了不能把清洗产物一起带走。"""
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"

    class Exploding:
        model_name = "exploding"

        def embed(self, texts):
            raise RuntimeError("模型下载失败")

    counts = run(src, out, run_id="idx4", embedder=Exploding())

    assert counts["index_status"] == "failed"
    assert counts["kept"] > 0
    assert (out / "knowledge").is_dir() and any((out / "knowledge").iterdir())
    assert not (out / "index.json").exists()
    assert not (out / "index-vectors.npy").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["index_status"] == "failed"
    assert manifest["index_reason"]


def test_partial_index_write_is_rolled_back(tmp_path, monkeypatch):
    """JSON 写失败时向量文件也不能留下——半写入的索引比没有索引更糟。"""
    import pathlib

    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    real_write = pathlib.Path.write_text

    def boom(self, *a, **k):
        if self.name == "index.json":
            raise OSError("磁盘满了")
        return real_write(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    counts = run(src, out, run_id="idx6", embedder=FakeEmbedder(dim=8))

    assert counts["index_status"] == "failed"
    assert (out / "knowledge").is_dir()
    assert not (out / "index.json").exists()
    assert not (out / "index-vectors.npy").exists()


def test_cli_returns_5_when_index_failed(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _corpus(src)

    def fake_run(*a, **k):
        return {"total": 14, "kept": 14, "dropped_stub": 0, "dropped_duplicate": 0,
                "index_status": "failed", "index_reason": "RuntimeError"}

    monkeypatch.setattr("kb_init.pipeline.run", fake_run)
    assert main([str(src), "-o", str(tmp_path / "out")]) == 5


def test_cli_no_index_flag_returns_zero(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-index"]) == 0


def test_keyboard_interrupt_is_not_swallowed_as_partial_success(tmp_path):
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"

    class Interrupting:
        model_name = "interrupting"

        def embed(self, texts):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(src, out, run_id="idx5", embedder=Interrupting())
    assert not out.exists()          # staging 被清理，不留半成品


def test_docs_without_chunks_still_get_an_assignment(tmp_path):
    """空正文文档切不出块、拿不到向量，仍必须有一条 residual assignment。"""
    src = tmp_path / "src"
    _corpus(src)
    # frontmatter-only 文档：标题来自 frontmatter，正文为空但字数够不上 kept ——
    # 这里直接构造一篇正文全是空白、但长度过阈的文档
    (src / "blank.md").write_text("# 空白\n\n" + " " * 400, encoding="utf-8")
    out = tmp_path / "out"
    counts = run(src, out, run_id="idx7", embedder=FakeEmbedder(dim=8))

    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    kept = [d["doc_id"] for d in manifest["documents"] if d["status"] == "kept"]
    assigned = [a["doc_id"] for a in index["analyses"][0]["assignments"]]
    assert sorted(assigned) == sorted(kept)
    assert counts["index_status"] == "complete"
