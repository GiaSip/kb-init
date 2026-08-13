"""把不可信输入（zip / 文件夹）安全地变成本地 .md 文件列表。

所有外部输入一律视为敌意输入：path traversal / zip bomb / symlink 循环 /
超大文件都必须在这一层挡掉，后续模块可以假定拿到的路径是安全的。
"""
from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 65_536  # 64 KiB — streaming 块大小


class UnsafeArchiveError(Exception):
    """归档包含不安全条目，或超出资源上限。"""


@dataclass(frozen=True)
class ExtractLimits:
    max_files: int = 50_000
    max_total_bytes: int = 2_000_000_000
    max_file_bytes: int = 50_000_000
    max_ratio: float = 100.0


def _check_entry_name(name: str) -> None:
    """在任何 I/O 前，拦截路径遍历与绝对路径条目。"""
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchiveError(f"absolute path entry rejected: {name!r}")
    parts = Path(name).parts
    if ".." in parts:
        raise UnsafeArchiveError(f"path traversal entry rejected: {name!r}")


def safe_extract(
    archive: Path, dest: Path, limits: ExtractLimits = ExtractLimits()
) -> Path:
    """把 zip 安全解压到 dest，返回解压根目录。

    安全保证（按层次）：
    1. 路径名检查：拦截 `..` / 绝对路径（在任何 I/O 发生前）。
    2. 条目数预检：用元数据做快速 count 检查（条目数不可伪造）。
    3. resolve() 双保险：即使 #1 漏网，resolve 后再比对路径边界。
       使用 Path.is_relative_to() 而非 startswith()——后者有前缀碰撞漏洞
       （/tmp/foo 会误放行 /tmp/foobar/evil 路径）。
    4. 流式读取 + 实际字节计数：不信 zip 元数据的 file_size / compress_size——
       恶意 zip 可以把元数据声明为极小值而实际解压体积极大。
       每个 chunk 写入前累加实际字节，超限即刻抛出。
    5. 压缩比用「实际解压总字节 / zip 文件真实磁盘大小」——zip 磁盘大小
       由 archive.stat().st_size 取得，无法被 zip 内容伪造。
    """
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    # zip 文件的真实磁盘大小：恶意 zip 内容无法伪造这个值
    zip_disk_size = archive.stat().st_size

    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()

        # 条目数快速预检（中央目录里的条目数不可伪造）
        if len(infos) > limits.max_files:
            raise UnsafeArchiveError(
                f"file count {len(infos)} exceeds limit {limits.max_files}"
            )

        # 路径名安全检查（所有 I/O 前）
        for info in infos:
            _check_entry_name(info.filename)

        dest_resolved = dest.resolve()
        total_written = 0

        for info in infos:
            if info.is_dir():
                continue

            target = dest / info.filename

            # resolve() 跟随 symlink，双重防止 path traversal。
            # is_relative_to() 比 startswith() 安全：
            #   startswith("/tmp/foo") 会误放行 "/tmp/foobar/evil"
            resolved = target.resolve()
            if not resolved.is_relative_to(dest_resolved):
                raise UnsafeArchiveError(
                    f"path traversal after resolve: {info.filename!r}"
                )

            resolved.parent.mkdir(parents=True, exist_ok=True)

            # 流式读取：按实际字节数检查，不信元数据的 file_size / compress_size
            file_written = 0
            with zf.open(info) as src, open(resolved, "wb") as out:
                while chunk := src.read(_CHUNK):
                    file_written += len(chunk)
                    running_total = total_written + file_written

                    if file_written > limits.max_file_bytes:
                        raise UnsafeArchiveError(
                            f"entry too large: {info.filename!r} "
                            f"(exceeds {limits.max_file_bytes} bytes)"
                        )
                    if running_total > limits.max_total_bytes:
                        raise UnsafeArchiveError(
                            f"total size {running_total} exceeds limit "
                            f"{limits.max_total_bytes}"
                        )
                    if zip_disk_size > 0:
                        ratio = running_total / zip_disk_size
                        if ratio > limits.max_ratio:
                            raise UnsafeArchiveError(
                                f"compression ratio {ratio:.1f} exceeds limit "
                                f"{limits.max_ratio}"
                            )
                    out.write(chunk)

            total_written += file_written

    return dest


def walk_source(
    source: Path, limits: ExtractLimits = ExtractLimits()
) -> list[Path]:
    """返回 source 下所有 .md 文件；source 是 zip 时先安全解压。

    绝不跟随 symlink——symlink 循环会让遍历永不终止。
    zip 路径：symlink / 文件数上限 / 单文件体积上限均生效：
      - safe_extract 流式挡超大文件（实际字节，不信元数据）
      - 提取后的目录遍历跳过 symlink（safe_extract 不会创建 symlink，
        但对目录输入依然需要此保护）
      - 目录遍历的文件计数同样受 max_files 约束
    注意：临时目录不会自动清理（清理会使返回的路径失效）。
    """
    source = Path(source)
    if source.is_file() and source.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="kb-init-"))
        source = safe_extract(source, tmp, limits)

    found: list[Path] = []
    stack = [source]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir()):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.suffix.lower() == ".md":
                if entry.stat().st_size > limits.max_file_bytes:
                    continue
                found.append(entry)
                if len(found) > limits.max_files:
                    raise UnsafeArchiveError(
                        f"file count exceeds limit {limits.max_files}"
                    )
    return sorted(found)
