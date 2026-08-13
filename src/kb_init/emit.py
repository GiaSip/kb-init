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
# group 1 = target（允许 # 锚点），group 2 = 可选别名
_WIKILINK = re.compile(r"\[\[([^\]\|]+?)(?:\|([^\]]+?))?\]\]")
# 围栏式代码块或行内反引号——替换时跳过其内容
_CODE_FENCE = re.compile(r"(```[\s\S]*?```|`[^`\n]+`)")


def _slugify(title: str, fallback: str) -> str:
    cleaned = _UNSAFE.sub("", title).strip().replace(" ", "-")
    return cleaned[:60] if cleaned else fallback


def _convert_links(body: str) -> str:
    def repl(match: re.Match) -> str:
        target_full = match.group(1).strip()
        label = (match.group(2) or target_full).strip()
        if "#" in target_full:
            target_file, anchor = target_full.split("#", 1)
            return f"[{label}]({target_file}.md#{anchor})"
        return f"[{label}]({target_full}.md)"

    # 分段处理：_CODE_FENCE.split 奇数索引为代码块，偶数索引为普通文本
    parts = _CODE_FENCE.split(body)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            result.append(_WIKILINK.sub(repl, part))
        else:
            result.append(part)
    return "".join(result)


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
        counter = 1
        while name in used:
            name = f"{slug}-{counter}.md"
            counter += 1
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
