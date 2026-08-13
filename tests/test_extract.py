import zipfile
from pathlib import Path

import pytest

from kb_init.extract import ExtractLimits, UnsafeArchiveError, safe_extract, walk_source


# NOTE: compression=ZIP_DEFLATED is intentional.
# With ZIP_STORED (the default), compress_size == file_size so the ratio is
# always 1.0 and test_zip_bomb_ratio_is_rejected can never trigger.
# ZIP_DEFLATED lets b"0" * 5_000_000 compress to ~5 KB, giving ratio >> 2.0.
def _make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_path_traversal_is_rejected(tmp_path):
    archive = _make_zip(tmp_path / "evil.zip", {"../../pwned.md": b"x"})
    with pytest.raises(UnsafeArchiveError, match="traversal"):
        safe_extract(archive, tmp_path / "out")


def test_absolute_path_entry_is_rejected(tmp_path):
    archive = _make_zip(tmp_path / "abs.zip", {"/etc/pwned.md": b"x"})
    with pytest.raises(UnsafeArchiveError, match="absolute"):
        safe_extract(archive, tmp_path / "out")


def test_too_many_files_is_rejected(tmp_path):
    entries = {f"n{i}.md": b"x" for i in range(20)}
    archive = _make_zip(tmp_path / "many.zip", entries)
    limits = ExtractLimits(max_files=10)
    with pytest.raises(UnsafeArchiveError, match="file count"):
        safe_extract(archive, tmp_path / "out", limits)


def test_zip_bomb_ratio_is_rejected(tmp_path):
    archive = _make_zip(tmp_path / "bomb.zip", {"big.md": b"0" * 5_000_000})
    limits = ExtractLimits(max_ratio=2.0)
    with pytest.raises(UnsafeArchiveError, match="compression ratio"):
        safe_extract(archive, tmp_path / "out", limits)


def test_normal_zip_extracts(tmp_path):
    archive = _make_zip(tmp_path / "ok.zip", {"a/b.md": b"hello"})
    root = safe_extract(archive, tmp_path / "out")
    assert (root / "a" / "b.md").read_bytes() == b"hello"


def test_walk_source_skips_symlinks(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "real.md").write_text("real")
    (src / "sub" / "nested.md").write_text("nested")
    (src / "link.md").symlink_to(src / "real.md")
    found = {p.name for p in walk_source(src)}
    assert found == {"real.md", "nested.md"}


def test_walk_source_accepts_zip(tmp_path):
    archive = _make_zip(tmp_path / "z.zip", {"a.md": b"hi"})
    found = walk_source(archive)
    assert [p.name for p in found] == ["a.md"]


# --- Additional tests verifying walk_source+zip enforces ALL limits ---


def test_walk_source_zip_nested_dirs_found(tmp_path):
    """zip 内嵌套目录的 .md 文件能被 walk_source 遍历到。"""
    archive = _make_zip(
        tmp_path / "nested.zip",
        {"top.md": b"t", "sub/deep.md": b"d", "sub/skip.txt": b"s"},
    )
    found_names = {p.name for p in walk_source(archive)}
    assert found_names == {"top.md", "deep.md"}


def test_walk_source_zip_bomb_rejected(tmp_path):
    """walk_source 调 safe_extract 时把 limits 传进去；zip bomb 在遍历前就被拦。"""
    archive = _make_zip(tmp_path / "bomb.zip", {"big.md": b"0" * 5_000_000})
    limits = ExtractLimits(max_ratio=2.0)
    with pytest.raises(UnsafeArchiveError, match="compression ratio"):
        walk_source(archive, limits)


def test_walk_source_zip_oversized_file_limit(tmp_path):
    """safe_extract 按实际流字节数挡超大文件，不信 zip 元数据声明的 file_size。"""
    # 用一个真实的大文件（1 MB），配 max_file_bytes=500 KB
    data = b"A" * (600 * 1024)  # 600 KB > 500 KB limit
    archive = _make_zip(tmp_path / "big.zip", {"large.md": data})
    limits = ExtractLimits(max_file_bytes=500 * 1024)
    with pytest.raises(UnsafeArchiveError):
        safe_extract(archive, tmp_path / "out", limits)
