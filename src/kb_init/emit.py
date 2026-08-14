"""唯一写产物的模块。

**两遍式**：第一遍为全部 kept 文档冻结路径并建立引用映射，第二遍才改写链接并落盘。
不能合成一遍——链接改写若发生在目标命名之前，产出的链接会指向不存在的路径
（`[[Project A]]` 写成 `(Project A.md)` 而实际 slug 是 `Project-A.md`）。

默认输出标准相对路径链接——[[wikilink]] 是 Obsidian/Roam 方言，
默认使用它等于隐性绑定 Obsidian，在 VS Code 里全是死链。
"""
from __future__ import annotations

import posixpath
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


@dataclass(frozen=True)
class _LinkIndex:
    """两种引用语义各用一张表，不能合并。

    `by_alias` 是**名字**语义（wikilink：Obsidian 按全库文件名解析，与目录无关）；
    `by_path` 是**路径**语义（标准 Markdown 链接：相对当前文档所在目录解析）。
    混用一张表就会拿名字去解释路径——`a/linker.md` 里的 `(note.md)` 被接到
    `b/note.md` 上，产出「活着的错链」。
    """

    by_alias: dict[str, str]
    by_path: dict[str, str]


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


def _freeze_paths(docs: list[Document]) -> _LinkIndex:
    """第一遍：为全部 kept 文档分配唯一文件名并冻结 out_relpath。

    同时建两张索引：
    - `by_alias`：「引用写法 → 文件名」。同一篇文档可被多种写法引用
      （标题 / 原文件名 stem / 原相对路径），全部登记；先到先得，不覆盖。
    - `by_path`：「源相对路径 → 文件名」，供标准 Markdown 相对链接按路径解析。
    """
    used_keys: set[str] = set()
    mapping: dict[str, str] = {}
    owners: dict[str, set[str]] = {}    # alias → 拥有它的 doc_id 集合
    by_path: dict[str, str] = {}
    path_owners: dict[str, set[str]] = {}

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
        path_key = _norm_key(posixpath.normpath(doc.source_relpath))
        path_owners.setdefault(path_key, set()).add(doc.doc_id)
        by_path.setdefault(path_key, name)
        # 不登记输出文件名自身：_rewrite_md_links 在 wikilink 转换之前执行，
        # 不存在二次处理，自映射只会让「输出名恰好等于另一篇的标题」时抢占别名。
        for alias in (doc.title, source.stem, source.name, doc.source_relpath):
            key = _norm_key(alias.strip()) if alias else ""
            if key:
                # 按 doc_id 去重：同一篇文档的 title 与 stem 可能相同，
                # 若按「出现次数」计会自我构成假歧义，把本来唯一的别名删掉，
                # 导致大量本应成功的链接退化成纯文本。
                owners.setdefault(key, set()).add(doc.doc_id)
                mapping.setdefault(key, name)

    # 歧义别名一律作废——先到先得会产生「活着的错链」：链接指向了错误的
    # 那一篇，而且不会记入 unresolved，manifest 反而显示解析成功。
    # 死链尚可被发现，错链不会。
    for key, doc_ids in owners.items():
        if len(doc_ids) > 1:
            mapping.pop(key, None)
    # 源路径本该天然唯一（walk_source 已按文件系统等价键拦过碰撞），这里是兜底：
    # 真出现两篇归一后同路径时宁可都不解析，也不赌其中一篇。
    for key, doc_ids in path_owners.items():
        if len(doc_ids) > 1:
            by_path.pop(key, None)
    return _LinkIndex(by_alias=mapping, by_path=by_path)


def _resolve_source_path(
    target: str, source_dir: str, by_path: dict[str, str]
) -> str | None:
    """按**路径**语义解析标准 Markdown 相对链接。

    基准是当前文档所在目录，其次是导出根（Obsidian 的「相对 vault 根」
    设置会把链接写成不带前导斜杠的根相对路径）。两者都是全路径精确匹配。

    **刻意不做 basename/stem 兜底**：`a/linker.md` 里的 `(note.md)` 在
    Markdown 语义下只可能是 `a/note.md`；仓库里只有 `b/note.md` 时把链接
    接过去，产出的是「活着的错链」——正文指向一篇不相干的文档，而 manifest
    显示解析成功。死链有人报，错链没人查，所以宁可降级为纯文本并记账。
    （wikilink 是名字语义，不受此限，走 `_resolve_target`。）
    """
    for base in (source_dir, ""):
        joined = posixpath.normpath(posixpath.join(base, target))
        if joined == ".." or joined.startswith("../"):
            continue                    # 逃出导出根的路径不可能对应任何文档
        hit = by_path.get(_norm_key(joined))
        if hit is not None:
            return hit
    return None


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
    text: str, index: _LinkIndex, unresolved: list[str], source_dir: str
) -> str:
    """重映射**原有的**标准相对链接。

    真实导出（尤其 Notion）里的内部链接不是 wikilink，而是形如
    `[标题](Some%20Page%20abc123.md)` 的 URL 编码相对路径。目录被拍平后
    这些路径全部失效——只处理 wikilink 会让真实语料 100% 死链。

    `source_dir` 是当前文档在源树中的目录（POSIX 相对路径，根目录为 ""）。
    没有它就只能拿 basename 猜，跨目录同名文件必然被接错。
    """

    def repl(match: re.Match) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#", "/")):
            return match.group(0)       # 外链与同文件锚点不动

        path_part, _, anchor = target.partition("#")
        decoded = unquote(path_part)
        if not decoded.lower().endswith(".md"):
            # 文件名本身含 `#` 的情形：Notion 允许页面标题以 `#` 开头，导出的
            # 文件名就带 `#` 且链接里不做 URL 编码。按锚点切完只剩目录部分，
            # 会让链接原样留下变成死链。先按锚点解释（上面），不成立再把整串
            # 当路径试一次——顺序不能反，否则 `a.md#b.md` 的锚点会被吞进路径。
            whole = unquote(target)
            if not whole.lower().endswith(".md"):
                return match.group(0)   # 非 .md 目标（图片等）不动
            decoded, anchor = whole, ""

        name = _resolve_source_path(decoded, source_dir, index.by_path)
        if name is None:
            unresolved.append(decoded)
            return label                # 不留死链
        suffix = f"#{anchor}" if anchor else ""
        return f"[{label}]({name}{suffix})"

    return _MDLINK.sub(repl, text)


def _convert_links(
    body: str,
    index: _LinkIndex,
    unresolved: list[str],
    source_dir: str,
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

        name = _resolve_target(target, index.by_alias)
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
            remapped = _rewrite_md_links(part, index, unresolved, source_dir)
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

    index = _freeze_paths(docs)             # 第一遍：冻结全部路径
    unresolved: list[dict] = []

    for doc in docs:                        # 第二遍：改写并落盘
        if doc.status != "kept":
            continue
        misses: list[str] = []
        # --wikilinks 只决定「是否保留 [[...]] 方言」，**不能**跳过标准
        # Markdown 链接的重映射——那些链接在目录拍平后同样会失效。
        body = _convert_links(
            doc.body,
            index,
            misses,
            posixpath.dirname(doc.source_relpath),
            keep_wikilinks=wikilinks,
        )
        for miss in misses:
            unresolved.append({"from_doc_id": doc.doc_id, "target": miss})

        name = Path(doc.out_relpath).name
        (knowledge / name).write_text(
            _frontmatter(doc) + body.lstrip("\n"), encoding="utf-8"
        )
    return EmitResult(documents=docs, unresolved_links=unresolved)
