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

    `ambiguous_aliases` 单独留着：解析失败有两种，处理方式不同——「从来没有过
    这个目标」在 wikilink 方言下是合法的未创建链接，可以原样保留；「匹配到多篇」
    则必须降级，否则 Obsidian 会替我们挑一篇，挑中哪篇没人知道。
    """

    by_alias: dict[str, str]
    by_path: dict[str, str]
    ambiguous_aliases: frozenset[str]


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
    ambiguous = {key for key, doc_ids in owners.items() if len(doc_ids) > 1}
    for key in ambiguous:
        mapping.pop(key, None)
    # 源路径本该天然唯一（walk_source 已按文件系统等价键拦过碰撞），这里是兜底：
    # 真出现两篇归一后同路径时宁可都不解析，也不赌其中一篇。
    for key, doc_ids in path_owners.items():
        if len(doc_ids) > 1:
            by_path.pop(key, None)
    return _LinkIndex(
        by_alias=mapping, by_path=by_path, ambiguous_aliases=frozenset(ambiguous)
    )


def _resolve_source_path(
    target: str, source_dir: str, by_path: dict[str, str]
) -> str | None:
    """按**路径**语义解析标准 Markdown 相对链接。

    基准**只有一个**：当前文档所在目录（CommonMark 语义）。曾经试过"当前目录
    不中就退回导出根"，那是在猜链接是用哪种基准写的——根目录不是"另一个可以
    试试的基准"，它就是另一个目录，接过去和接到 `b/note.md` 是同一类错链。

    **刻意不做 basename/stem 兜底**：`a/linker.md` 里的 `(note.md)` 在
    Markdown 语义下只可能是 `a/note.md`；仓库里只有 `b/note.md` 时把链接
    接过去，产出的是「活着的错链」——正文指向一篇不相干的文档，而 manifest
    显示解析成功。死链有人报，错链没人查，所以宁可降级为纯文本并记账。
    （wikilink 是名字语义，不受此限，走 `_resolve_target`。）
    """
    joined = posixpath.normpath(posixpath.join(source_dir, target))
    if joined == ".." or joined.startswith("../"):
        return None                     # 逃出导出根的路径不可能对应任何文档
    return by_path.get(_norm_key(joined))


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


def _is_ambiguous(target: str, index: _LinkIndex) -> bool:
    """该引用写法是否匹配到多篇文档（登记时已作废，此处只回答"为什么失败"）。

    查法必须与 `_resolve_target` 一致：同样要试剥掉 `.md` 后缀的写法，
    否则 `[[foo.md]]` 的歧义会被误判成"从来没有过"。
    """
    key = _norm_key(target)
    if key in index.ambiguous_aliases:
        return True
    if target.lower().endswith(".md"):
        return _norm_key(target[:-3]) in index.ambiguous_aliases
    return False


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

        # `#` 在链接里有两种身份，只看字符分不出来：锚点分隔符，或文件名的
        # 一部分（Notion 允许页面标题以 `#` 开头，导出的文件名就带 `#`，且
        # 链接里不做 URL 编码）。所以按每个 `#` 的位置逐个生成候选，由
        # by_path 的实际命中来裁决——从最早的切分点开始，整串当文件名放最后，
        # 保证常规的 `foo.md#小节` 优先按锚点解释。
        splits = [(target[:i], target[i + 1:]) for i, ch in enumerate(target) if ch == "#"]
        splits.append((target, ""))
        candidates = [
            (unquote(path_part), anchor)
            for path_part, anchor in splits
            if unquote(path_part).lower().endswith(".md")
        ]
        if not candidates:
            return match.group(0)       # 非 .md 目标（图片等）不动

        for decoded, anchor in candidates:
            name = _resolve_source_path(decoded, source_dir, index.by_path)
            if name is not None:
                suffix = f"#{anchor}" if anchor else ""
                return f"[{label}]({name}{suffix})"

        unresolved.append(candidates[0][0])
        return label                    # 不留死链

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
                # [[#小节]] 同文件锚点
                return match.group(0) if keep_wikilinks else f"[{label}](#{anchor})"

        name = _resolve_target(target, index.by_alias)
        suffix = f"#{anchor}" if anchor else ""
        if name is not None:
            if not keep_wikilinks:
                return f"[{label}]({name}{suffix})"
            # 方言模式同样要重写：输出文件名是 slug 化过的（`Project A` →
            # `Project-A.md`），原样留着 `[[Project A]]` 在 Obsidian 里一样点不开。
            stem = name[:-3] if name.lower().endswith(".md") else name
            return f"[[{stem}{suffix}]]" if stem == label else f"[[{stem}{suffix}|{label}]]"

        if keep_wikilinks and not _is_ambiguous(target, index):
            # 方言模式下「目标从来没有过」是合法的未创建链接（Obsidian 里点击
            # 即新建），保留原文；但仍记账，让 manifest 说得清有多少悬空引用。
            unresolved.append(target)
            return match.group(0)

        # 目标不存在（从未有过，或被判空壳/重复而没有输出文件），或别名歧义。
        # 绝不产生指向不存在文件的链接，也绝不把歧义交给 Obsidian 去挑一篇
        # ——退化为纯文本并记账。
        unresolved.append(target)
        return label

    # 分段处理：_CODE_FENCE.split 奇数索引为代码块，偶数索引为普通文本
    parts = _CODE_FENCE.split(body)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # 顺序要紧：先重映射原有标准链接，再把 wikilink 转成标准链接。
            # 反过来会让刚生成的链接被再处理一次（自映射保证幂等，但多余）。
            remapped = _rewrite_md_links(part, index, unresolved, source_dir)
            # wikilink 一律要过 repl，keep_wikilinks 只改**输出语法**，不是
            # 跳过解析：跳过就等于把「目标叫什么」交给 Obsidian 猜，slug 化后
            # 的输出名和歧义别名都会静默指错。
            result.append(_WIKILINK.sub(repl, remapped))
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
