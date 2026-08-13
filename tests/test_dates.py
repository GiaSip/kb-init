import subprocess
from pathlib import Path

from kb_init.dates import resolve_date
from kb_init.model import Document


def _doc(**kwargs) -> Document:
    base = dict(
        doc_id="0" * 16,
        source_relpath="a.md",
        content_hash="1" * 16,
        title="A",
        body="",
        frontmatter={},
    )
    base.update(kwargs)
    return Document(**base)


def test_level1_frontmatter_created_wins(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(frontmatter={"created": "2023-05-01", "date": "2024-01-01"},
               body="写于 2022-03-03")
    assert resolve_date(doc, f) == ("2023-05-01", "frontmatter")


def test_level1_accepts_date_key_too(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(frontmatter={"date": "2024-01-02"})
    assert resolve_date(doc, f) == ("2024-01-02", "frontmatter")


def test_level2_body_date(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(body="随手记于 2022/03/03 的想法")
    assert resolve_date(doc, f) == ("2022-03-03", "body")


def test_level3_filename_date(tmp_path):
    f = tmp_path / "2021-07-09-会议.md"
    f.write_text("x")
    doc = _doc(source_relpath="2021-07-09-会议.md", body="无日期")
    assert resolve_date(doc, f) == ("2021-07-09", "filename")


def test_level4_git_first_commit(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    f = tmp_path / "a.md"
    f.write_text("x")
    subprocess.run(["git", "add", "a.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "x", "--date", "2020-02-02T00:00:00"],
        cwd=tmp_path, check=True,
        env={"GIT_COMMITTER_DATE": "2020-02-02T00:00:00", "PATH": "/usr/bin:/bin"},
    )
    doc = _doc(body="无日期")
    assert resolve_date(doc, f) == ("2020-02-02", "git")


def test_level5_unknown_when_nothing_available(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(body="完全没有日期")
    assert resolve_date(doc, f) == (None, "unknown")


def test_invalid_date_feb30_returns_unknown(tmp_path):
    """2024-02-30 是历法上不存在的日期，必须返回 unknown 而非假 ISO 字符串。"""
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(body="写于 2024-02-30 的内容")
    assert resolve_date(doc, f) == (None, "unknown")


def test_invalid_date_apr31_returns_unknown(tmp_path):
    """2023-04-31 是历法上不存在的日期（小月），必须返回 unknown。"""
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(body="写于 2023-04-31 的内容")
    assert resolve_date(doc, f) == (None, "unknown")


def test_never_reads_mtime(tmp_path, monkeypatch):
    """守卫测试：任何分支都不得读取 mtime / ctime。

    覆盖五条访问路径：Path.stat / Path.lstat / os.stat / os.path.getmtime /
    os.path.getctime。只要实现里任一路径回退到 mtime，这个测试就会红。
    """
    import os

    f = tmp_path / "a.md"
    f.write_text("x")

    class ExplodingStat:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __getattr__(self, name):
            if name in ("st_mtime", "st_mtime_ns", "st_ctime", "st_ctime_ns"):
                raise AssertionError(f"实现读取了不可信的 {name}")
            return getattr(self._wrapped, name)

    # Path.stat
    original_path_stat = Path.stat

    def guarded_path_stat(self, *args, **kwargs):
        return ExplodingStat(original_path_stat(self, *args, **kwargs))

    monkeypatch.setattr(Path, "stat", guarded_path_stat)

    # Path.lstat
    original_path_lstat = Path.lstat

    def guarded_path_lstat(self, *args, **kwargs):
        return ExplodingStat(original_path_lstat(self, *args, **kwargs))

    monkeypatch.setattr(Path, "lstat", guarded_path_lstat)

    # os.stat
    original_os_stat = os.stat

    def guarded_os_stat(*args, **kwargs):
        return ExplodingStat(original_os_stat(*args, **kwargs))

    monkeypatch.setattr(os, "stat", guarded_os_stat)

    # os.path.getmtime / os.path.getctime — 直接炸
    def exploding_getmtime(p):
        raise AssertionError("实现读取了不可信的 st_mtime via os.path.getmtime")

    def exploding_getctime(p):
        raise AssertionError("实现读取了不可信的 st_ctime via os.path.getctime")

    monkeypatch.setattr(os.path, "getmtime", exploding_getmtime)
    monkeypatch.setattr(os.path, "getctime", exploding_getctime)

    doc = _doc(body="没有日期")
    result, source = resolve_date(doc, f)
    assert result is None and source == "unknown"
