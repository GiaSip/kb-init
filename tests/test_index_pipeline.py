import json

import pytest

from kb_init.cli import main
from kb_init.pipeline import run
from tests.fakes import BlobEmbedder, FakeEmbedder

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


def test_index_import_failure_still_publishes_cleaned_output(tmp_path, monkeypatch):
    """索引专属依赖导入失败（如平台缺 sklearn wheel）也必须被吸收。

    这是 R15 点名的跨平台风险：导入若在窄 try 之外，异常会穿透到 ExitStack，
    staging 被删，清洗产物一起消失——而那正是退出码 5 承诺不会发生的事。
    """
    import builtins

    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sklearn.cluster" or name.startswith("kb_init.cluster"):
            raise ImportError("平台缺 sklearn wheel")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    counts = run(src, out, run_id="imp", embedder=FakeEmbedder(dim=8))

    assert counts["index_status"] == "failed"
    assert counts["index_reason"] == "runtime_unavailable"
    assert (out / "knowledge").is_dir() and any((out / "knowledge").iterdir())


def test_reason_codes_are_stable_identifiers_not_exception_names(tmp_path):
    """reason 必须是稳定枚举值，异常类名会随实现细节漂移。"""
    src = tmp_path / "src"
    _corpus(src)

    class Exploding:
        model_name = "x"

        def embed(self, texts):
            raise RuntimeError("推理炸了")

    counts = run(src, tmp_path / "out", run_id="rc", embedder=Exploding())
    assert counts["index_reason"] == "inference_failed"


def test_empty_corpus_still_writes_a_valid_index(tmp_path):
    """零 kept 文档不能是「complete 但没有 index 文件」——那是说谎的状态。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "stub.md").write_text("# 短\n\n短", encoding="utf-8")
    out = tmp_path / "out"
    counts = run(src, out, run_id="empty", embedder=FakeEmbedder(dim=8))

    assert counts["kept"] == 0
    assert counts["index_status"] == "complete"
    assert (out / "index.json").exists(), "complete 就必须有 index 文件"
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["analyses"][0]["assignments"] == []
    assert index["vector_doc_ids"] == []


def test_vector_rows_are_explicitly_mapped_to_doc_ids(tmp_path):
    """行序不能只靠约定：显式记 vector_doc_ids，且必须与矩阵行数一致。"""
    import numpy as np

    src = tmp_path / "src"
    _corpus(src)
    (src / "blank.md").write_text("# 空白\n\n" + " " * 400, encoding="utf-8")
    out = tmp_path / "out"
    run(src, out, run_id="vecmap", embedder=FakeEmbedder(dim=8))

    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    matrix = np.load(out / "index-vectors.npy")
    assert len(index["vector_doc_ids"]) == matrix.shape[0]
    # 切不出块的文档有 assignment 但没有向量行——两者数量本就可以不等
    assigned = {a["doc_id"] for a in index["analyses"][0]["assignments"]}
    assert set(index["vector_doc_ids"]) <= assigned


def test_provenance_reflects_injected_embedder_not_fastembed(tmp_path):
    """注入假 embedder 时不能仍在产物里声称用的是 fastembed。"""
    src = tmp_path / "src"
    _corpus(src)
    out = tmp_path / "out"
    run(src, out, run_id="prov", embedder=FakeEmbedder(dim=8))
    versions = json.loads((out / "index.json").read_text(encoding="utf-8"))["versions"]
    assert "fastembed" not in versions["embedder_adapter"]
    assert {"python", "numpy", "sklearn", "kb_init"} <= set(versions)


def test_classifier_never_raises_even_when_embed_module_is_broken(monkeypatch):
    """异常分类器必须是全函数：它跑在 except 分支里，自己一抛就把原异常放出去了。"""
    import builtins

    from kb_init.pipeline import _classify_index_failure

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("kb_init.embed"):
            raise ImportError("numpy 没装")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _classify_index_failure(RuntimeError("x")) == "inference_failed"
    assert _classify_index_failure(ImportError("y")) == "runtime_unavailable"
    assert _classify_index_failure(FileNotFoundError("z")) == "model_unavailable"


def test_zip_scratch_that_cannot_be_removed_aborts_before_publishing(tmp_path, monkeypatch):
    """明文临时目录删不掉就不许发布——否则一边承诺全程本地不留痕，一边把明文留在盘上。"""
    import shutil
    import zipfile

    src_zip = tmp_path / "corpus.zip"
    with zipfile.ZipFile(src_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(12):
            zf.writestr(f"doc{i:02d}.md", f"# 标题{i}\n\n{LONG}第{i}篇")

    real_rmtree = shutil.rmtree

    def stubborn(path, *a, **k):
        if "kb-init-" in str(path) and ".kb-init-staging" not in str(path):
            return                      # 假装删了，其实没删
        return real_rmtree(path, *a, **k)

    monkeypatch.setattr("kb_init.pipeline.shutil.rmtree", stubborn)
    out = tmp_path / "out"
    with pytest.raises(OSError, match="明文残留"):
        run(src_zip, out, run_id="zipfail", embedder=FakeEmbedder(dim=8))
    assert not out.exists(), "删不掉明文就不能发布产物"


def test_empty_corpus_does_not_touch_the_model_or_sklearn(tmp_path, monkeypatch):
    """零 kept 文档时不该加载 90MB 模型，也不该让写空索引依赖 sklearn 装没装好。"""
    import builtins

    src = tmp_path / "src"
    src.mkdir()
    (src / "stub.md").write_text("# 短\n\n短", encoding="utf-8")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("sklearn") or name == "fastembed":
            raise ImportError(f"{name} 不该在空语料路径被导入")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = tmp_path / "out"
    counts = run(src, out, run_id="empty2")

    assert counts["index_status"] == "complete"
    assert (out / "index.json").exists()


# ---------------- 2A′：过大簇细分接线 ----------------

def _blob_corpus(tmp_path, blobs):
    """blobs: [(标记, 篇数)]。正文里的 `blob:<标记>` 由 BlobEmbedder 解释成方向。

    正文必须超过 clean.py 的 min_body_chars=200，否则整批被判空壳、kept=0，
    测试会在一个「什么都没有」的索引上空转还全绿。
    """
    src = tmp_path / "src"
    src.mkdir()
    for marker, count in blobs:
        for i in range(count):
            (src / f"{marker}-{i:02d}.md").write_text(
                f"# {marker} {i}\n\nblob:{marker}\n" + ("内容内容内容内容 " * 40),
                encoding="utf-8")
    return src


def _shaped(tmp_path):
    """两个紧致簇 + 一批各自为政的噪声 → 保证既有 group 也有 residual。"""
    return _blob_corpus(tmp_path, [("alpha", 8), ("beta", 8), ("noise", 12)])


def test_shaped_corpus_really_produces_groups_and_residual(tmp_path):
    """先证明 fixture 本身有效——否则下面几条都在空索引上空转。"""
    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    cov = index["analyses"][0]["coverage"]
    assert cov["assigned"] >= 10 and cov["residual"] >= 5
    assert len(index["analyses"][0]["groups"]) >= 2


def test_root_method_records_its_own_selection_method_and_threshold(tmp_path):
    """参数不落盘 = 产物隐瞒了自己是怎么来的。"""
    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    params = index["analyses"][0]["method"]["params"]
    assert params["cluster_selection_method"] == "eom"
    assert params["cohesion_lift_min"] == 0.12


def test_tight_groups_are_not_flagged(tmp_path):
    """负例：形状明显的语料上不该有任何 group 被细分。"""
    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert len(index["analyses"]) == 1


def test_subdivision_appends_a_well_formed_child_analysis(tmp_path, monkeypatch):
    """正例：强制标记一个真实存在的 group，验证细分产物结构合法。

    检测逻辑本身由 test_subdivide.py 用精确几何覆盖；这里只测**接线**。
    """
    import kb_init.subdivide as sd

    monkeypatch.setattr(sd, "flagged_groups", lambda lifts, *a, **k: sorted(lifts)[:1])
    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert len(index["analyses"]) == 2, "被标记的 group 必须产出一项子分析"
    child = index["analyses"][1]
    assert child["parent_analysis_id"] == "topics-01"
    assert child["input_scope"]["kind"] == "parent_group"
    assert child["method"]["params"]["cluster_selection_method"] == "leaf"
    # 子分析恰好覆盖父 group 成员——validate_index 已在写盘前查过，这里再钉一次
    parent_gid = child["input_scope"]["group_id"]
    parent_members = {
        a["doc_id"] for a in index["analyses"][0]["assignments"]
        for m in a["memberships"] if m["group_id"] == parent_gid
    }
    assert parent_members
    assert {a["doc_id"] for a in child["assignments"]} == parent_members


def test_index_is_deterministic_across_runs(tmp_path):
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    src = _shaped(tmp_path)
    run(src, out_a, embedder=BlobEmbedder(), run_id="t")
    run(src, out_b, embedder=BlobEmbedder(), run_id="t")
    a = json.loads((out_a / "index.json").read_text(encoding="utf-8"))
    b = json.loads((out_b / "index.json").read_text(encoding="utf-8"))
    assert a == b


def test_subdivision_failure_rolls_back_the_whole_index(tmp_path, monkeypatch):
    import kb_init.subdivide as sd

    monkeypatch.setattr(sd, "flagged_groups", lambda lifts, *a, **k: sorted(lifts)[:1])
    monkeypatch.setattr(sd, "subdivide_group",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸")))
    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    assert summary["index_status"] == "failed"
    assert not (out / "index.json").exists()
    assert not (out / "index-vectors.npy").exists()
    assert (out / "knowledge").is_dir()              # 清洗产物必须还在


# ---------------- 2B：洞察阶段接线 ----------------

def test_insights_are_published_alongside_the_index(tmp_path):
    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    assert summary["insights_status"] == "complete"
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "t"
    assert payload["counts"]["total"] == len(payload["insights"])
    assert payload["counts"]["topic"] >= 2
    assert (out / "insights.md").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["insights_status"] == "complete"
    assert manifest["insights_reason"] is None


def test_insights_md_validates_against_its_own_json(tmp_path):
    from kb_init.insights_md import validate_markdown

    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    validate_markdown((out / "insights.md").read_text(encoding="utf-8"), payload)


def test_insights_bind_to_the_same_corpus_hash_as_the_manifest(tmp_path):
    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert payload["corpus_hash"] == manifest["corpus_hash"]


def test_no_index_skips_insights(tmp_path):
    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, no_index=True)
    assert summary["insights_status"] == "skipped"
    assert summary["insights_reason"] == "no_index"
    assert not (out / "insights.json").exists()
    assert not (out / "insights.md").exists()


def test_index_failure_skips_insights(tmp_path):
    from tests.fakes import BrokenEmbedder

    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, embedder=BrokenEmbedder("nan"), run_id="t")
    assert summary["index_status"] == "failed"
    assert summary["insights_status"] == "skipped"
    assert summary["insights_reason"] == "index_failed"
    assert (out / "knowledge").is_dir()


def test_insights_failure_keeps_the_index_and_marks_status(tmp_path, monkeypatch):
    import kb_init.insights as mod

    monkeypatch.setattr(mod, "build_insight_set",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸")))
    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    assert summary["index_status"] == "complete"
    assert summary["insights_status"] == "failed"
    assert summary["insights_reason"] == "naming_failed"
    assert (out / "index.json").exists()
    assert not (out / "insights.json").exists()
    assert not (out / "insights.md").exists()


def test_half_written_insights_are_rolled_back(tmp_path, monkeypatch):
    """写 json 成功、写 md 失败 → 两个都不能留下。"""
    from pathlib import Path as _P

    real = _P.write_text

    def explode(self, *a, **k):
        if self.name == "insights.md":
            raise OSError("写 md 失败")
        return real(self, *a, **k)

    monkeypatch.setattr(_P, "write_text", explode)
    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    monkeypatch.undo()
    assert summary["insights_status"] == "failed"
    assert not (out / "insights.json").exists()
    assert not (out / "insights.md").exists()
    assert (out / "index.json").exists()


def test_cleanup_failure_never_destroys_completed_products(tmp_path, monkeypatch):
    """清理路径放异常出去，就会穿到 run() 的 finally 把清洗产物一起删掉。

    构造：写洞察时炸 + 清理时也删不掉。断言清洗产物与索引都还在，
    且真相记在 manifest 里（insights_status=failed / io_failed）。
    """
    import kb_init.insights as mod

    monkeypatch.setattr(mod, "build_insight_set",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸")))
    monkeypatch.setattr(mod, "cleanup_insight_files",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("删不掉")))
    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    assert summary["insights_status"] == "failed"
    assert summary["insights_reason"] == "io_failed"
    assert (out / "knowledge").is_dir()              # 清洗产物必须还在
    assert (out / "index.json").exists()             # 索引也是完好的
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["insights_status"] == "failed"


def test_index_cleanup_failure_never_destroys_cleaned_output(tmp_path, monkeypatch):
    """索引层的同一条路径（2A 遗留）。"""
    import kb_init.index as mod

    monkeypatch.setattr(mod, "cleanup_index_files",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("删不掉")))
    from tests.fakes import BrokenEmbedder

    out = tmp_path / "out"
    summary = run(_shaped(tmp_path), out, embedder=BrokenEmbedder("nan"), run_id="t")
    assert summary["index_status"] == "failed"
    assert summary["index_reason"] == "io_failed"
    assert (out / "knowledge").is_dir()


def test_run_rejects_an_illegal_provenance_at_the_entrance(tmp_path):
    """放到洞察阶段才抛的话，会被那一层的异常吸收器变成 insights_status=failed，
    程序化调用方永远拿不到 ValueError。"""
    import pytest

    with pytest.raises(ValueError, match="corpus_provenance"):
        run(_shaped(tmp_path), tmp_path / "out", embedder=BlobEmbedder(),
            run_id="t", corpus_provenance="thirdparty")


def test_provisional_manifest_is_never_published(tmp_path):
    """pending 只是给洞察阶段读索引用的中间态，绝不能出现在发布出去的产物里。"""
    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["insights_status"] == "complete"


def test_provisional_manifest_is_also_finalised_when_insights_fail(tmp_path, monkeypatch):
    import kb_init.insights as mod

    monkeypatch.setattr(mod, "build_insight_set",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸")))
    out = tmp_path / "out"
    run(_shaped(tmp_path), out, embedder=BlobEmbedder(), run_id="t")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["insights_status"] == "failed"
