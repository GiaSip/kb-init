import pytest
from kb_init.cli import main


def test_version_flag_prints_version(capsys):
    rc = main(["--version"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() != ""


def test_no_args_returns_usage_error():
    assert main([]) == 2


def test_missing_source_path_gives_clean_error(tmp_path, capsys):
    """不存在的输入路径必须给退出码 3 + 单行诊断，不吐 traceback。"""
    rc = main([str(tmp_path / "不存在"), "-o", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 3
    assert "Traceback" not in err
    assert "错误：" in err


def test_corrupt_zip_gives_clean_error(tmp_path, capsys):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip at all")
    rc = main([str(bad), "-o", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 3
    assert "Traceback" not in err


def _fake_summary(**over):
    base = {"total": 10, "kept": 6, "dropped_stub": 4, "dropped_duplicate": 0,
            "index_status": "complete", "index_reason": None,
            "insights_status": "complete", "insights_reason": None}
    base.update(over)
    return base


def test_exit_code_6_when_only_insights_failed(tmp_path, monkeypatch, capsys):
    from kb_init.cli import main

    monkeypatch.setattr("kb_init.pipeline.run",
                        lambda *a, **k: _fake_summary(insights_status="failed",
                                                      insights_reason="naming_failed"))
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 6
    assert "洞察" in capsys.readouterr().err


def test_exit_code_5_still_wins_when_index_failed(tmp_path, monkeypatch):
    from kb_init.cli import main

    monkeypatch.setattr("kb_init.pipeline.run",
                        lambda *a, **k: _fake_summary(
                            index_status="failed", index_reason="model_unavailable",
                            insights_status="skipped", insights_reason="index_failed"))
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 5


def test_exit_code_0_when_everything_completes(tmp_path, monkeypatch):
    from kb_init.cli import main

    monkeypatch.setattr("kb_init.pipeline.run", lambda *a, **k: _fake_summary())
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 0


# ---------------- kb-init validate ----------------

def _write_pair(tmp_path, insights_status="complete"):
    import json

    from kb_init.insights_md import render_markdown

    payload = {
        "schema_version": "0.1", "run_id": "r1", "corpus_hash": "c1",
        "counts": {"topic": 1, "residual": 0, "corpus": 0, "total": 1},
        "presentation": {"group_refs": [],
                         "truncated": {"shown": 1, "total": 1,
                                       "omitted_group_refs": [], "omitted_docs": 0}},
        "insights": [{"insight_id": "T1", "family": "topic",
                      "kind": "topic_cluster", "canonical_text": "文本",
                      "payload": {}, "evidence": {"doc_ids": [], "stat": None},
                      "claude_md": None}],
    }
    (tmp_path / "insights.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "insights.md").write_text(render_markdown(payload), encoding="utf-8")
    if insights_status is not None:
        (tmp_path / "manifest.json").write_text(
            json.dumps({"insights_status": insights_status, "insights_reason": None}),
            encoding="utf-8")
    return payload


def test_validate_accepts_a_matching_pair(tmp_path, capsys):
    from kb_init.cli import main

    _write_pair(tmp_path)
    assert main(["validate", str(tmp_path / "insights.md")]) == 0
    assert "1 条" in capsys.readouterr().out


def test_validate_rejects_unknown_id_with_line_number(tmp_path, capsys):
    from kb_init.cli import main

    _write_pair(tmp_path)
    path = tmp_path / "insights.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n- [x] `T9` 冒出来的\n",
                    encoding="utf-8")
    assert main(["validate", str(path)]) == 7
    err = capsys.readouterr().err
    assert "T9" in err and "行" in err


def test_validate_reports_missing_json_clearly(tmp_path, capsys):
    from kb_init.cli import main

    _write_pair(tmp_path)
    (tmp_path / "insights.json").unlink()
    assert main(["validate", str(tmp_path / "insights.md")]) == 7
    assert "insights.json" in capsys.readouterr().err


def test_validate_requires_exactly_one_path(tmp_path):
    from kb_init.cli import main

    assert main(["validate"]) == 2


def test_normal_run_still_works_after_adding_the_subcommand(tmp_path):
    """加子命令最容易踩的坑：把原来的 `kb-init <source>` 用法弄坏。"""
    from kb_init.cli import main

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("# a\n\n" + "内容内容内容 " * 60, encoding="utf-8")
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-index"]) == 0


def test_a_directory_literally_named_validate_is_still_processable(tmp_path, monkeypatch):
    """无条件按首参数分流会吃掉一个合法的 source 名。"""
    from kb_init.cli import main

    monkeypatch.chdir(tmp_path)
    src = tmp_path / "validate"
    src.mkdir()
    (src / "a.md").write_text("# a\n\n" + "内容内容内容 " * 60, encoding="utf-8")
    assert main(["validate", "-o", str(tmp_path / "out"), "--no-index"]) == 0
    assert (tmp_path / "out" / "knowledge").is_dir()


def test_corpus_provenance_flag_reaches_the_gate(tmp_path):
    """provenance 只换了默认值、调用方从不传的话，条件③永远 not_evaluable，
    那个机制就只是摆设。"""
    import json

    from kb_init.cli import main

    src = tmp_path / "src"
    src.mkdir()
    for i in range(14):
        (src / f"d{i:02d}.md").write_text(
            f"# 标题{i}\n\nblob:alpha\n" + ("内容内容内容内容 " * 40), encoding="utf-8")
    out = tmp_path / "out"
    import kb_init.pipeline as pl
    from tests.fakes import BlobEmbedder

    real_run = pl.run
    pl.run = lambda *a, **k: real_run(*a, **{**k, "embedder": BlobEmbedder()})
    try:
        assert main([str(src), "-o", str(out), "--corpus-provenance", "third-party"]) == 0
    finally:
        pl.run = real_run
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    gate = payload["revisit_gate"]
    assert gate["inputs"]["corpus_provenance"] == "third_party"
    states = {c["id"]: c["state"] for c in gate["conditions"]}
    assert states["residual_high"] != "not_evaluable"


def test_validate_refuses_when_manifest_says_insights_failed(tmp_path, capsys):
    import json

    from kb_init.cli import main

    _write_pair(tmp_path, insights_status="failed")
    assert main(["validate", str(tmp_path / "insights.md")]) == 7
    assert "complete" in capsys.readouterr().err


def test_validate_accepts_when_manifest_says_complete(tmp_path):
    import json

    from kb_init.cli import main

    _write_pair(tmp_path)
    assert main(["validate", str(tmp_path / "insights.md")]) == 0


def test_validate_refuses_when_manifest_is_missing(tmp_path, capsys):
    """「读不到就跳过」是兜底路径的经典形态——read_index 那边已经拒读，
    这里放行就是两个入口两套标准。"""
    from kb_init.cli import main

    _write_pair(tmp_path, insights_status=None)
    assert main(["validate", str(tmp_path / "insights.md")]) == 7
    assert "insights_status" in capsys.readouterr().err


def test_validate_refuses_when_manifest_is_corrupt(tmp_path):
    from kb_init.cli import main

    _write_pair(tmp_path, insights_status=None)
    (tmp_path / "manifest.json").write_text("{ 这不是 json", encoding="utf-8")
    assert main(["validate", str(tmp_path / "insights.md")]) == 7


def test_validate_refuses_when_the_status_field_is_absent(tmp_path):
    import json

    from kb_init.cli import main

    _write_pair(tmp_path, insights_status=None)
    (tmp_path / "manifest.json").write_text(json.dumps({"run_id": "r1"}),
                                            encoding="utf-8")
    assert main(["validate", str(tmp_path / "insights.md")]) == 7


def test_validate_refuses_when_manifest_top_level_is_not_an_object(tmp_path):
    """合法 JSON 但顶层是数组/null/字符串时，下标会抛 TypeError——
    read_index 那边已经捕了，这里不能漏，否则同一种输入两个入口两种行为。"""
    from kb_init.cli import main

    for payload in ("[]", "null", '"just a string"'):
        _write_pair(tmp_path, insights_status=None)
        (tmp_path / "manifest.json").write_text(payload, encoding="utf-8")
        assert main(["validate", str(tmp_path / "insights.md")]) == 7, payload
