"""Markdown 文本 → Document 结构。只负责解析，不做任何判定或写盘。"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from kb_init.model import Document, compute_content_hash, compute_doc_id

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
_MAX_FRONTMATTER_BYTES = 64 * 1024


def _split_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    body = text[match.end():]
    if len(match.group(1)) > _MAX_FRONTMATTER_BYTES:
        # yaml.safe_load 不暴露大小限制接口，锚点展开（&a [*a,*a]*a）可指数级
        # 耗内存。原始文件 50MB 上限挡不住解析型 DoS，在这里加块级上限。
        return {}, body
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, body
    return (data if isinstance(data, dict) else {}), body


def _pick_title(frontmatter: dict, body: str, path: Path) -> str:
    fm_title = frontmatter.get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()
    h1 = _H1.search(body)
    if h1:
        return h1.group(1).strip()
    return path.stem


def parse_file(path: Path, root: Path) -> Document:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    frontmatter, body = _split_frontmatter(text)
    relpath = path.relative_to(root).as_posix()
    return Document(
        doc_id=compute_doc_id(relpath),
        source_relpath=relpath,
        content_hash=compute_content_hash(raw),
        title=_pick_title(frontmatter, body, path),
        body=body,
        frontmatter=frontmatter,
        created=None,
        date_source="unresolved",
    )
