"""新鲜度降级链。

⚠️ 绝不使用 st_mtime。实测：已维护 vault 的"陈旧率 >180 天"算出 0%，
因为 Obsidian sync / git / 批量操作都会刷新 mtime。所有人第一反应会用的
新鲜度代理是坏的——宁可返回 unknown 也不猜。
"""
from __future__ import annotations

import datetime
import re
import subprocess
from pathlib import Path

from kb_init.model import Document

# 前后数字边界不可省：没有它会从更长数字串里截出 1234-5-6（法规/SKU/工程编号
# 密集的语料里会明显聚集），而正文首个匹配会被直接升级为 created 且静默进 manifest
_DATE_PATTERN = re.compile(r"(?<!\d)(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?!\d)")


def _normalize(y: str, m: str, d: str) -> str | None:
    try:
        year, month, day = int(y), int(m), int(d)
        datetime.date(year, month, day)  # 验证历法合法性，拒绝 2024-02-30 等无效日期
    except ValueError:
        return None
    if not 1900 <= year <= 2100:
        # datetime.date 接受 1-9999，范围太宽会把"第 1234-5-6 条"当成日期。
        # 这个区间检查曾在改用 datetime.date 校验时被一并误删（回归）。
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _from_text(text: str) -> str | None:
    match = _DATE_PATTERN.search(text)
    if not match:
        return None
    return _normalize(*match.groups())


def _from_git(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "log", "--follow", "--diff-filter=A",
             "--format=%ad", "--date=short", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


def resolve_date(doc: Document, path: Path) -> tuple[str | None, str]:
    for key in ("created", "date"):
        value = doc.frontmatter.get(key)
        if value is not None:
            resolved = _from_text(str(value))
            if resolved:
                return resolved, "frontmatter"

    resolved = _from_text(doc.body)
    if resolved:
        return resolved, "body"

    resolved = _from_text(Path(doc.source_relpath).name)
    if resolved:
        return resolved, "filename"

    resolved = _from_git(Path(path))
    if resolved:
        return resolved, "git"

    return None, "unknown"
