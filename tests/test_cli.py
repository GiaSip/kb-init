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
