"""唯一写产物的模块。

**两遍式**：第一遍为全部 kept 文档冻结路径并建立引用映射，第二遍才改写链接并落盘。
不能合成一遍——链接改写若发生在目标命名之前，产出的链接会指向不存在的路径
（`[[Project A]]` 写成 `(Project A.md)` 而实际 slug 是 `Project-A.md`）。

默认输出标准相对路径链接——[[wikilink]] 是 Obsidian/Roam 方言，
默认使用它等于隐性绑定 Obsidian，在 VS Code 里全是死链。
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kb_init.model import Document

_UNSAFE = re.compile(r"[^\w一-鿿\- ]+")
# group 1 = target（允许 # 锚点），group 2 = 可选别名
_WIKILINK = re.compile(r"\[\[([^\]\|]+?)(?:\|([^\]]+?))?\]\]")
# 围栏式代码块或行内反引号——替换时跳过其内容
_CODE_FENCE = re.compile(r"(```[\s\S]*?```|`[^`\n]+`)")
# 已有的标准 Markdown 链接：group 1 = label, group 2 = target
_MDLINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


@dataclass
class EmitResult:
    documents: list[Document]
    unresolved_links: list[dict] = field(default_factory=list)


def _norm_key(text: str) -> str:
    """文件系统等价键：NFC 归一 + casefold。

    macOS 与 Windows 默认大小写不敏感，且 NFC/NFD 在 macOS 上互为等价。
    不做这层归一，`A.md` 与 `a.md` 会在写盘时互相覆盖，而 manifest 仍
    声称两篇都保留、各有不同路径——静默丢文档。
    """
    return unicodedata.normalize("NFC", text).casefold()


def _slugify(title: str, fallback: str) -> str:
    cleaned = _UNSAFE.sub("", title).strip().replace(" ", "-")
    return cleaned[:60] if cleaned else fallback


def _freeze_paths(docs: list[Document]) -> dict[str, str]:
    """第一遍：为全部 kept 文档分配唯一文件名并冻结 out_relpath。

    返回「引用写法 → 文件名」的映射。同一篇文档可被多种写法引用
    （标题 / 原文件名 stem / 原相对路径），全部登记；先到先得，不覆盖。
    """
    used_keys: set[str] = set()
    mapping: dict[str, str] = {}
    counts: dict[str, int] = {}

    for doc in docs:
        if doc.status != "kept":
            continue
        slug = _slugify(doc.title, doc.doc_id)
        name = f"{slug}.md"
        counter = 1
        while _norm_key(name) in used_keys:
            name = f"{slug}-{counter}.md"
            counter += 1
        used_keys.add(_norm_key(name))
        doc.out_relpath = f"knowledge/{name}"

        source = Path(doc.source_relpath)
        # 不登记输出文件名自身：_rewrite_md_links 在 wikilink 转换之前执行，
        # 不存在二次处理，自映射只会让「输出名恰好等于另一篇的标题」时抢占别名。
        for alias in (doc.title, source.stem, source.name, doc.source_relpath):
            key = _norm_key(alias.strip()) if alias else ""
            if key:
                counts[key] = counts.get(key, 0) + 1
                mapping.setdefault(key, name)

    # 歧义别名一律作废——先到先得会产生「活着的错链」：链接指向了错误的
    # 那一篇，而且不会记入 unresolved，manifest 反而显示解析成功。
    # 死链尚可被发现，错链不会。
    for key, n in counts.items():
        if n > 1:
            mapping.pop(key, None)
    return mapping


def _resolve_target(target: str, mapping: dict[str, str]) -> str | None:
    """按引用写法查出实际文件名；查不到返回 None。"""
    hit = mapping.get(_norm_key(target))
    if hit is not None:
        return hit
    # `[[foo.md]]` 这类自带后缀的写法：剥掉后缀再查一次，
    # 否则会拼出 foo.md.md
    if target.lower().endswith(".md"):
        return mapping.get(_norm_key(target[:-3]))
    return None


def _rewrite_md_links(
    text: str, mapping: dict[str, str], unresolved: list[str]
) -> str:
    """重映射**原有的**标准相对链接。

    真实导出（尤其 Notion）里的内部链接不是 wikilink，而是形如
    `[标题](Some%20Page%20abc123.md)` 的 URL 编码相对路径。目录被拍平后
    这些路径全部失效——只处理 wikilink 会让真实语料 100% 死链。
    """

    def repl(match: re.Match) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#", "/")):
            return match.group(0)       # 外链与同文件锚点不动

        path_part, _, anchor = target.partition("#")
        decoded = unquote(path_part)
        if not decoded.lower().endswith(".md"):
            return match.group(0)       # 非 .md 目标（图片等）不动

        candidate = Path(decoded)
        name = (
            _resolve_target(decoded, mapping)
            or _resolve_target(candidate.name, mapping)
            or _resolve_target(candidate.stem, mapping)
        )
        if name is None:
            unresolved.append(decoded)
            return label                # 不留死链
        suffix = f"#{anchor}" if anchor else ""
        return f"[{label}]({name}{suffix})"

    return _MDLINK.sub(repl, text)


def _convert_links(
    body: str,
    mapping: dict[str, str],
    unresolved: list[str],
    keep_wikilinks: bool = False,
) -> str:
    def repl(match: re.Match) -> str:
        raw = match.group(1).strip()
        label = (match.group(2) or raw).strip()

        anchor = ""
        target = raw
        if "#" in raw:
            target, anchor = raw.split("#", 1)
            target = target.strip()
            if not target:
                return f"[{label}](#{anchor})"  # [[#小节]] 同文件锚点

        name = _resolve_target(target, mapping)
        if name is None:
            # 目标不存在（从未有过，或被判空壳/重复而没有输出文件）。
            # 绝不产生指向不存在文件的链接——退化为纯文本并记账。
            unresolved.append(target)
            return label
        suffix = f"#{anchor}" if anchor else ""
        return f"[{label}]({name}{suffix})"

    # 分段处理：_CODE_FENCE.split 奇数索引为代码块，偶数索引为普通文本
    parts = _CODE_FENCE.split(body)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # 顺序要紧：先重映射原有标准链接，再把 wikilink 转成标准链接。
            # 反过来会让刚生成的链接被再处理一次（自映射保证幂等，但多余）。
            remapped = _rewrite_md_links(part, mapping, unresolved)
            result.append(
                remapped if keep_wikilinks else _WIKILINK.sub(repl, remapped)
            )
        else:
            result.append(part)
    return "".join(result)


def _frontmatter(doc: Document) -> str:
    """用 YAML serializer 生成前置块。

    绝不字符串插值——source_relpath 来自不可信输入，Unix/ZIP 文件名允许换行，
    `x\\n---\\nstatus: forged` 能提前闭合 frontmatter 污染产物与后续解析。
    """
    payload = {
        "doc_id": doc.doc_id,
        "source": doc.source_relpath,
        "created": doc.created or "unknown",
        "date_source": doc.date_source,
    }
    dumped = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    return f"---\n{dumped}---\n\n"


def emit(
    docs: list[Document], out_dir: Path, wikilinks: bool = False
) -> EmitResult:
    out_dir = Path(out_dir)
    knowledge = out_dir / "knowledge"
    if knowledge.exists() and any(knowledge.iterdir()):
        raise FileExistsError(
            f"输出目录已存在内容，拒绝覆盖：{knowledge}。请换一个 --out 目录。"
        )
    knowledge.mkdir(parents=True, exist_ok=True)

    mapping = _freeze_paths(docs)          # 第一遍：冻结全部路径
    unresolved: list[dict] = []

    for doc in docs:                        # 第二遍：改写并落盘
        if doc.status != "kept":
            continue
        misses: list[str] = []
        # --wikilinks 只决定「是否保留 [[...]] 方言」，**不能**跳过标准
        # Markdown 链接的重映射——那些链接在目录拍平后同样会失效。
        body = _convert_links(doc.body, mapping, misses, keep_wikilinks=wikilinks)
        for miss in misses:
            unresolved.append({"from_doc_id": doc.doc_id, "target": miss})

        name = Path(doc.out_relpath).name
        (knowledge / name).write_text(
            _frontmatter(doc) + body.lstrip("\n"), encoding="utf-8"
        )
    return EmitResult(documents=docs, unresolved_links=unresolved)
