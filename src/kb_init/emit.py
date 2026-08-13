"""唯一写产物的模块。

路径在此冻结：out_relpath 一旦设定，后续所有证据引用都指向它。
默认输出标准相对路径链接——[[wikilink]] 是 Obsidian/Roam 方言，
默认使用它等于隐性绑定 Obsidian，在 VS Code 里全是死链。
"""
from __future__ import annotations

import re
from pathlib import Path

from kb_init.model import Document

_UNSAFE = re.compile(r"[^\w一-鿿\- ]+")
_WIKILINK = re.compile(r"\[\[([^\]\|#]+?)(?:\|([^\]]+?))?\]\]")


def _slugify(title: str, fallback: str) -> str:
    cleaned = _UNSAFE.sub("", title).strip().replace(" ", "-")
    return cleaned[:60] if cleaned else fallback


def _convert_links(body: str) -> str:
    def repl(match: re.Match) -> str:
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()
        return f"[{label}]({target}.md)"
    return _WIKILINK.sub(repl, body)


def emit(
    docs: list[Document], out_dir: Path, wikilinks: bool = False
) -> list[Document]:
    out_dir = Path(out_dir)
    knowledge = out_dir / "knowledge"
    if knowledge.exists() and any(knowledge.iterdir()):
        raise FileExistsError(
            f"输出目录已存在内容，拒绝覆盖：{knowledge}。请换一个 --out 目录。"
        )
    knowledge.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    for doc in docs:
        if doc.status != "kept":
            continue
        slug = _slugify(doc.title, doc.doc_id)
        name = f"{slug}.md"
        if name in used:
            name = f"{slug}-{doc.doc_id[:6]}.md"
        used.add(name)

        body = doc.body if wikilinks else _convert_links(doc.body)
        header = [
            "---",
            f"doc_id: {doc.doc_id}",
            f"source: {doc.source_relpath}",
            f"created: {doc.created or 'unknown'}",
            f"date_source: {doc.date_source}",
            "---",
            "",
        ]
        target = knowledge / name
        tmp = target.with_suffix(".md.tmp")
        tmp.write_text("\n".join(header) + body.lstrip("\n"), encoding="utf-8")
        tmp.replace(target)          # 原子落盘
        doc.out_relpath = f"knowledge/{name}"
    return docs
