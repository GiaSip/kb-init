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
    (src / "real.md").write_text("real", encoding="utf-8")
    (src / "sub" / "nested.md").write_text("nested", encoding="utf-8")
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


def test_safe_extract_rejects_oversized_file(tmp_path):
    """streaming 字节计数在超过 max_file_bytes 时即刻抛出（正常元数据，准确的 file_size）。

    本测试验证「流式阈值」有效性，而非「伪造元数据绕过」场景。
    原因：Python zipfile 用 info.file_size 限制解压输出量（ZipExtFile._left），
    伪造 file_size 为极小值不会让实际数据绕过检查——只有声明的字节数到达调用方，
    因此 min(claimed_size, actual_size) 自动受限，磁盘耗尽攻击无法通过此路径实施。
    流式方案的价值是内存安全（不在 RAM 里缓冲整个文件）和及早失败。
    """
    data = b"A" * (600 * 1024)  # 600 KB > 500 KB limit
    archive = _make_zip(tmp_path / "big.zip", {"large.md": data})
    limits = ExtractLimits(max_file_bytes=500 * 1024)
    with pytest.raises(UnsafeArchiveError):
        safe_extract(archive, tmp_path / "out", limits)


def test_walk_source_dir_nonmd_count_enforces_limit(tmp_path):
    """目录输入时，非 .md 文件也计入 total_seen，防止用大量 .txt 文件绕过 max_files。

    zip 路径：safe_extract 在入口处用 len(infos) 统计所有条目（含 .txt）。
    目录路径：修复前只统计 .md 文件，攻击者可塞入任意数量 .txt 绕过限制；
              修复后 total_seen 统计所有文件条目，保持语义对称。
    """
    src = tmp_path / "src"
    src.mkdir()
    for i in range(15):
        (src / f"file{i}.txt").write_text("x", encoding="utf-8")  # 15 .txt，零 .md
    limits = ExtractLimits(max_files=10)
    with pytest.raises(UnsafeArchiveError, match="file count"):
        walk_source(src, limits)
