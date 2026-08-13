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
