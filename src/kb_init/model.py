"""中间表示（IR）的核心数据结构。

doc_id 在管线第一步分配且此后永不改变——清洗、拍平、重命名都只改状态，
不改身份。这是证据链接能跨阶段保持有效的前提。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def compute_doc_id(source_relpath: str) -> str:
    """基于原始相对路径的稳定身份。同一份语料重跑必然得到同一个 id。"""
    return hashlib.sha256(source_relpath.encode("utf-8")).hexdigest()[:16]


def compute_content_hash(raw: bytes) -> str:
    """基于原始字节的内容指纹，用于去重。"""
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class Document:
    doc_id: str
    source_relpath: str
    content_hash: str
    title: str
    body: str
    frontmatter: dict = field(default_factory=dict)
    created: str | None = None
    date_source: str = "unknown"
    status: str = "kept"          # kept | dropped
    drop_reason: str | None = None
    out_relpath: str | None = None
