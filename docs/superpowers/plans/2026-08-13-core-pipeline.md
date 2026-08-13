# kb-init 核心管线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把任意笔记导出（文件夹或 zip）安全地归一成带稳定身份的干净 Markdown 知识库，并冻结输出路径供后续洞察层引用证据。

**Architecture:** 单向管线 `解压 → 解析 → 定身份 → 定日期 → 标清洗 → 落盘 → 写 manifest`。核心是一份**版本化中间表示（IR）**：每篇文档在第一步就获得稳定 `doc_id`，清洗只改状态不删记录，输出路径在落盘时冻结并写进 manifest——后续洞察层的证据链接全部指向这些冻结路径。

**Tech Stack:** Python 3.12 / uv / pytest / PyYAML（仅用于 frontmatter 解析）

## Global Constraints

以下约束来自 `docs/DESIGN.md`，**每个任务的要求都隐含包含本节**：

- Python **3.12+**，包管理与分发一律用 **uv**；首发入口是 `uvx kb-init`
- **禁止依赖 Obsidian**。产物必须在 VS Code / 任意编辑器中可用
- 内部链接**默认输出标准相对路径** `[标题](path.md)`；`[[wikilink]]` 只在显式 `--wikilinks` 时产生
- **清洗是标记不是删除**：产出 `kept / dropped + reason`，绝不真删记录（否则 "620 → 242" 这个核心数字和证据追踪都会丢）
- **输出路径必须在生成任何证据引用之前冻结**
- **每步 checkpoint**：任一阶段失败不得使前序产物报废
- **输出到新目录 + 原子落盘**，默认**不覆盖**已存在的产物
- **mtime 不可信**（实测：优等生 vault 陈旧率算出 0%，因 sync/git 会刷新 mtime）。新鲜度必须走 §5.1 降级链
- **所有外部输入视为不可信**：zip path traversal / zip bomb / symlink 循环 / 超大文件 / 正文中的 HTML 与 `<script>`
- 本计划**不涉及** embedding、聚类、LLM 调用、HTML 渲染——那些属于 Plan 2

---

## File Structure

```
pyproject.toml                      uv 项目定义 + console_scripts 入口
src/kb_init/__init__.py             版本号
src/kb_init/cli.py                  argparse 入口，子命令分发
src/kb_init/model.py                Document dataclass + doc_id/content_hash 计算
src/kb_init/extract.py              安全解压与安全遍历（R13）
src/kb_init/parse.py                Markdown + frontmatter 解析
src/kb_init/dates.py                新鲜度降级链（§5.1）
src/kb_init/clean.py                清洗标记（空壳 / 重复）
src/kb_init/emit.py                 落盘 knowledge/*.md，冻结路径
src/kb_init/manifest.py             manifest 读写 + corpus_hash
tests/test_extract.py               安全解压（含恶意 zip 三项）
tests/test_model.py                 doc_id 稳定性
tests/test_parse.py                 frontmatter / 正文切分
tests/test_dates.py                 降级链五级
tests/test_clean.py                 空壳与重复标记
tests/test_emit.py                  路径冻结、不覆盖、链接方言
tests/test_manifest.py              manifest schema
tests/test_e2e.py                   端到端
```

**职责边界**：`extract` 只负责"把不可信输入安全地变成本地文件列表"；`parse` 只负责"文本 → 结构"；`clean` 只做判定不做删除；`emit` 是唯一写产物的地方。任何模块都不得跨层直接写文件。

---

### Task 1: 项目骨架与 CLI 入口

**Files:**
- Create: `pyproject.toml`
- Create: `src/kb_init/__init__.py`
- Create: `src/kb_init/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 无
- Produces: `kb_init.__version__: str`；`kb_init.cli.main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_cli.py
import pytest
from kb_init.cli import main


def test_version_flag_prints_version(capsys):
    rc = main(["--version"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() != ""


def test_no_args_returns_usage_error():
    assert main([]) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init'`

- [ ] **Step 3: 写最小实现**

```toml
# pyproject.toml
[project]
name = "kb-init"
version = "0.1.0"
description = "Compile your old note exports into a knowledge base your AI agent can actually use"
requires-python = ">=3.12"
dependencies = ["PyYAML>=6.0"]

[project.scripts]
kb-init = "kb_init.cli:main_entry"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/kb_init"]

[dependency-groups]
dev = ["pytest>=8.0"]
```

```python
# src/kb_init/__init__.py
__version__ = "0.1.0"
```

```python
# src/kb_init/cli.py
import argparse
import sys

from kb_init import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kb-init",
        description="把笔记导出编译成 AI 能用的知识库",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--wikilinks",
        action="store_true",
        help="输出 [[wikilink]] 方言（默认输出标准相对路径链接）",
    )
    parser.add_argument("source", nargs="?", help="导出文件夹或 zip 路径")
    parser.add_argument("-o", "--out", default="kb-out", help="输出目录（默认 kb-out）")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.source is None:
        parser.print_usage(sys.stderr)
        return 2
    return 0


def main_entry() -> None:
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml src/kb_init/__init__.py src/kb_init/cli.py tests/test_cli.py
git commit -m "feat: 项目骨架与 CLI 入口"
```

---

### Task 2: 安全解压与安全遍历（R13）

**Files:**
- Create: `src/kb_init/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `kb_init.extract.ExtractLimits` — dataclass，字段 `max_files: int = 50_000`、`max_total_bytes: int = 2_000_000_000`、`max_file_bytes: int = 50_000_000`、`max_ratio: float = 100.0`
  - `kb_init.extract.UnsafeArchiveError(Exception)`
  - `kb_init.extract.safe_extract(archive: Path, dest: Path, limits: ExtractLimits = ExtractLimits()) -> Path`
  - `kb_init.extract.walk_source(source: Path, limits: ExtractLimits = ExtractLimits()) -> list[Path]` — 返回 `.md` 文件绝对路径列表，**不跟随 symlink**

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_extract.py
import zipfile
from pathlib import Path

import pytest

from kb_init.extract import ExtractLimits, UnsafeArchiveError, safe_extract, walk_source


def _make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
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
    (src / "real.md").write_text("real")
    (src / "sub" / "nested.md").write_text("nested")
    (src / "link.md").symlink_to(src / "real.md")
    found = {p.name for p in walk_source(src)}
    assert found == {"real.md", "nested.md"}


def test_walk_source_accepts_zip(tmp_path):
    archive = _make_zip(tmp_path / "z.zip", {"a.md": b"hi"})
    found = walk_source(archive)
    assert [p.name for p in found] == ["a.md"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_extract.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.extract'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/extract.py
"""把不可信输入（zip / 文件夹）安全地变成本地 .md 文件列表。

所有外部输入一律视为敌意输入：path traversal / zip bomb / symlink 循环 /
超大文件都必须在这一层挡掉，后续模块可以假定拿到的路径是安全的。
"""
from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


class UnsafeArchiveError(Exception):
    """归档包含不安全条目，或超出资源上限。"""


@dataclass(frozen=True)
class ExtractLimits:
    max_files: int = 50_000
    max_total_bytes: int = 2_000_000_000
    max_file_bytes: int = 50_000_000
    max_ratio: float = 100.0


def _check_entry_name(name: str) -> None:
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchiveError(f"absolute path entry rejected: {name!r}")
    parts = Path(name).parts
    if ".." in parts:
        raise UnsafeArchiveError(f"path traversal entry rejected: {name!r}")


def safe_extract(
    archive: Path, dest: Path, limits: ExtractLimits = ExtractLimits()
) -> Path:
    """把 zip 安全解压到 dest，返回解压根目录。"""
    archive = Path(archive)
    dest = Path(dest)
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > limits.max_files:
            raise UnsafeArchiveError(
                f"file count {len(infos)} exceeds limit {limits.max_files}"
            )
        total_uncompressed = 0
        total_compressed = 0
        for info in infos:
            _check_entry_name(info.filename)
            if info.file_size > limits.max_file_bytes:
                raise UnsafeArchiveError(
                    f"entry too large: {info.filename!r} ({info.file_size} bytes)"
                )
            total_uncompressed += info.file_size
            total_compressed += info.compress_size
        if total_uncompressed > limits.max_total_bytes:
            raise UnsafeArchiveError(
                f"total size {total_uncompressed} exceeds limit {limits.max_total_bytes}"
            )
        if total_compressed > 0:
            ratio = total_uncompressed / total_compressed
            if ratio > limits.max_ratio:
                raise UnsafeArchiveError(
                    f"compression ratio {ratio:.1f} exceeds limit {limits.max_ratio}"
                )
        dest.mkdir(parents=True, exist_ok=True)
        for info in infos:
            if info.is_dir():
                continue
            target = dest / info.filename
            resolved = target.resolve()
            if not str(resolved).startswith(str(dest.resolve())):
                raise UnsafeArchiveError(
                    f"path traversal after resolve: {info.filename!r}"
                )
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(resolved, "wb") as out:
                out.write(src.read())
    return dest


def walk_source(
    source: Path, limits: ExtractLimits = ExtractLimits()
) -> list[Path]:
    """返回 source 下所有 .md 文件；source 是 zip 时先安全解压。

    绝不跟随 symlink——symlink 循环会让遍历永不终止。
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_extract.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/extract.py tests/test_extract.py
git commit -m "feat: 安全解压与安全遍历，挡 traversal/bomb/symlink"
```

---

### Task 3: Document 模型与稳定 doc_id

**Files:**
- Create: `src/kb_init/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `kb_init.model.Document` — dataclass，字段：`doc_id: str`、`source_relpath: str`、`content_hash: str`、`title: str`、`body: str`、`frontmatter: dict`、`created: str | None`、`date_source: str`、`status: str = "kept"`、`drop_reason: str | None = None`、`out_relpath: str | None = None`
  - `kb_init.model.compute_doc_id(source_relpath: str) -> str` — 16 位 hex，仅依赖路径，跨 run 稳定
  - `kb_init.model.compute_content_hash(raw: bytes) -> str` — 16 位 hex，用于去重

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_model.py
from kb_init.model import Document, compute_content_hash, compute_doc_id


def test_doc_id_is_stable_across_calls():
    assert compute_doc_id("a/b.md") == compute_doc_id("a/b.md")


def test_doc_id_differs_by_path():
    assert compute_doc_id("a/b.md") != compute_doc_id("a/c.md")


def test_doc_id_is_16_hex_chars():
    value = compute_doc_id("a/b.md")
    assert len(value) == 16
    assert all(c in "0123456789abcdef" for c in value)


def test_content_hash_ignores_path():
    assert compute_content_hash(b"same") == compute_content_hash(b"same")
    assert compute_content_hash(b"a") != compute_content_hash(b"b")


def test_document_defaults_to_kept():
    doc = Document(
        doc_id="0" * 16,
        source_relpath="a.md",
        content_hash="1" * 16,
        title="A",
        body="body",
        frontmatter={},
        created=None,
        date_source="unknown",
    )
    assert doc.status == "kept"
    assert doc.drop_reason is None
    assert doc.out_relpath is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_model.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.model'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/model.py
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_model.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/model.py tests/test_model.py
git commit -m "feat: Document IR 模型与稳定 doc_id"
```

---

### Task 4: Markdown 与 frontmatter 解析

**Files:**
- Create: `src/kb_init/parse.py`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: `kb_init.model.Document`、`compute_doc_id`、`compute_content_hash`
- Produces: `kb_init.parse.parse_file(path: Path, root: Path) -> Document` — 读盘并构造 Document，`created` 与 `date_source` 此时留空（`None` / `"unresolved"`），由 Task 5 填充

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_parse.py
from pathlib import Path

from kb_init.parse import parse_file


def test_parses_frontmatter_and_body(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("---\ntitle: 我的笔记\ntags: [a, b]\n---\n\n正文内容\n", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.frontmatter["title"] == "我的笔记"
    assert doc.frontmatter["tags"] == ["a", "b"]
    assert doc.body.strip() == "正文内容"


def test_title_falls_back_to_h1_then_filename(tmp_path):
    with_h1 = tmp_path / "x.md"
    with_h1.write_text("# 标题在正文\n\n内容", encoding="utf-8")
    assert parse_file(with_h1, tmp_path).title == "标题在正文"

    bare = tmp_path / "只有文件名.md"
    bare.write_text("没有标题", encoding="utf-8")
    assert parse_file(bare, tmp_path).title == "只有文件名"


def test_malformed_frontmatter_does_not_crash(tmp_path):
    f = tmp_path / "bad.md"
    f.write_text("---\n: : : not yaml : :\n---\n正文", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.frontmatter == {}
    assert "正文" in doc.body


def test_relpath_and_ids_are_set(tmp_path):
    sub = tmp_path / "a"
    sub.mkdir()
    f = sub / "b.md"
    f.write_text("hi", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.source_relpath == "a/b.md"
    assert len(doc.doc_id) == 16
    assert len(doc.content_hash) == 16
    assert doc.date_source == "unresolved"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_parse.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.parse'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/parse.py
"""Markdown 文本 → Document 结构。只负责解析，不做任何判定或写盘。"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from kb_init.model import Document, compute_content_hash, compute_doc_id

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    body = text[match.end():]
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
    text = raw.decode("utf-8", errors="replace")
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_parse.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/parse.py tests/test_parse.py
git commit -m "feat: Markdown 与 frontmatter 解析"
```

---

### Task 5: 新鲜度降级链（mtime 不可信）

**Files:**
- Create: `src/kb_init/dates.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: `kb_init.model.Document`
- Produces: `kb_init.dates.resolve_date(doc: Document, path: Path) -> tuple[str | None, str]` — 返回 `(ISO 日期或 None, 来源标签)`，来源标签取值：`frontmatter` / `body` / `filename` / `git` / `unknown`

**背景**：实测证明 `mtime` 完全不可信——已维护 vault 的"陈旧率 >180 天"算出 0%，原因是 Obsidian sync / git / 批量操作会刷新 mtime。**本模块任何分支都不得读取 `st_mtime`。**

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_dates.py
import subprocess
from pathlib import Path

from kb_init.dates import resolve_date
from kb_init.model import Document


def _doc(**kwargs) -> Document:
    base = dict(
        doc_id="0" * 16,
        source_relpath="a.md",
        content_hash="1" * 16,
        title="A",
        body="",
        frontmatter={},
    )
    base.update(kwargs)
    return Document(**base)


def test_level1_frontmatter_created_wins(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(frontmatter={"created": "2023-05-01", "date": "2024-01-01"},
               body="写于 2022-03-03")
    assert resolve_date(doc, f) == ("2023-05-01", "frontmatter")


def test_level1_accepts_date_key_too(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(frontmatter={"date": "2024-01-02"})
    assert resolve_date(doc, f) == ("2024-01-02", "frontmatter")


def test_level2_body_date(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(body="随手记于 2022/03/03 的想法")
    assert resolve_date(doc, f) == ("2022-03-03", "body")


def test_level3_filename_date(tmp_path):
    f = tmp_path / "2021-07-09-会议.md"
    f.write_text("x")
    doc = _doc(source_relpath="2021-07-09-会议.md", body="无日期")
    assert resolve_date(doc, f) == ("2021-07-09", "filename")


def test_level4_git_first_commit(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    f = tmp_path / "a.md"
    f.write_text("x")
    subprocess.run(["git", "add", "a.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "x", "--date", "2020-02-02T00:00:00"],
        cwd=tmp_path, check=True,
        env={"GIT_COMMITTER_DATE": "2020-02-02T00:00:00", "PATH": "/usr/bin:/bin"},
    )
    doc = _doc(body="无日期")
    assert resolve_date(doc, f) == ("2020-02-02", "git")


def test_level5_unknown_when_nothing_available(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    doc = _doc(body="完全没有日期")
    assert resolve_date(doc, f) == (None, "unknown")


def test_never_reads_mtime(tmp_path, monkeypatch):
    """守卫测试：任何分支都不得读取 mtime。

    把 st_mtime 变成会爆炸的属性——只要实现里有任何一处回退到 mtime，
    这个测试就会红。仅断言"返回 unknown"是不够的：那种写法在实现
    偷偷用了 mtime 时依然会通过。
    """
    import os

    f = tmp_path / "a.md"
    f.write_text("x")

    real_stat = os.stat_result

    class ExplodingStat:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __getattr__(self, name):
            if name in ("st_mtime", "st_mtime_ns", "st_ctime", "st_ctime_ns"):
                raise AssertionError(f"实现读取了不可信的 {name}")
            return getattr(self._wrapped, name)

    original = Path.stat

    def guarded(self, *args, **kwargs):
        return ExplodingStat(original(self, *args, **kwargs))

    monkeypatch.setattr(Path, "stat", guarded)

    doc = _doc(body="没有日期")
    result, source = resolve_date(doc, f)
    assert result is None and source == "unknown"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_dates.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.dates'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/dates.py
"""新鲜度降级链。

⚠️ 绝不使用 st_mtime。实测：已维护 vault 的"陈旧率 >180 天"算出 0%，
因为 Obsidian sync / git / 批量操作都会刷新 mtime。所有人第一反应会用的
新鲜度代理是坏的——宁可返回 unknown 也不猜。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from kb_init.model import Document

_DATE_PATTERN = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")


def _normalize(y: str, m: str, d: str) -> str | None:
    try:
        year, month, day = int(y), int(m), int(d)
    except ValueError:
        return None
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_dates.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/dates.py tests/test_dates.py
git commit -m "feat: 新鲜度降级链，禁用不可信的 mtime"
```

---

### Task 6: 清洗标记（标记不删除）

**Files:**
- Create: `src/kb_init/clean.py`
- Test: `tests/test_clean.py`

**Interfaces:**
- Consumes: `kb_init.model.Document`
- Produces:
  - `kb_init.clean.CleanConfig` — dataclass，字段 `min_body_chars: int = 200`
  - `kb_init.clean.mark(docs: list[Document], config: CleanConfig = CleanConfig()) -> list[Document]` — **原地改 status/drop_reason 并返回同一列表，长度永不变化**
  - `kb_init.clean.summarize(docs: list[Document]) -> dict[str, int]` — 返回 `{"total": n, "kept": n, "dropped_stub": n, "dropped_duplicate": n}`

**背景**：实测 Notion 导出 1925 篇里 1149 篇 <200 字节（60% 空壳）、Apple Notes 620 篇里 249 篇空壳（40%）。"扔掉了多少"本身就是产品最有说服力的数字，**所以绝不能真删——删了这个数字就没了**。

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_clean.py
from kb_init.clean import CleanConfig, mark, summarize
from kb_init.model import Document


def _doc(doc_id: str, body: str, content_hash: str = None) -> Document:
    return Document(
        doc_id=doc_id,
        source_relpath=f"{doc_id}.md",
        content_hash=content_hash or doc_id.ljust(16, "0"),
        title="t",
        body=body,
        frontmatter={},
    )


def test_short_body_marked_as_stub():
    docs = mark([_doc("a", "太短")])
    assert docs[0].status == "dropped"
    assert docs[0].drop_reason == "stub"


def test_long_body_is_kept():
    docs = mark([_doc("a", "x" * 500)])
    assert docs[0].status == "kept"
    assert docs[0].drop_reason is None


def test_duplicate_marked_with_first_doc_id():
    docs = mark([
        _doc("aaa", "x" * 500, content_hash="H" * 16),
        _doc("bbb", "x" * 500, content_hash="H" * 16),
    ])
    assert docs[0].status == "kept"
    assert docs[1].status == "dropped"
    assert docs[1].drop_reason == "duplicate:aaa"


def test_list_length_never_shrinks():
    """核心不变量：清洗是标记不是删除。"""
    inputs = [_doc(str(i), "短") for i in range(10)]
    assert len(mark(inputs)) == 10


def test_summarize_counts_by_reason():
    docs = mark([
        _doc("a", "x" * 500, content_hash="H" * 16),
        _doc("b", "x" * 500, content_hash="H" * 16),
        _doc("c", "短"),
    ])
    assert summarize(docs) == {
        "total": 3, "kept": 1, "dropped_stub": 1, "dropped_duplicate": 1,
    }


def test_threshold_is_configurable():
    docs = mark([_doc("a", "x" * 100)], CleanConfig(min_body_chars=50))
    assert docs[0].status == "kept"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_clean.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.clean'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/clean.py
"""清洗判定。只标记，绝不删除记录。

"620 → 242" 这样的留存数字是产品最有说服力的证明；真删记录就再也算不出来了，
证据追踪也会断。
"""
from __future__ import annotations

from dataclasses import dataclass

from kb_init.model import Document


@dataclass(frozen=True)
class CleanConfig:
    min_body_chars: int = 200


def mark(docs: list[Document], config: CleanConfig = CleanConfig()) -> list[Document]:
    seen: dict[str, str] = {}
    for doc in docs:
        if len(doc.body.strip()) < config.min_body_chars:
            doc.status = "dropped"
            doc.drop_reason = "stub"
            continue
        first = seen.get(doc.content_hash)
        if first is not None:
            doc.status = "dropped"
            doc.drop_reason = f"duplicate:{first}"
            continue
        seen[doc.content_hash] = doc.doc_id
        doc.status = "kept"
        doc.drop_reason = None
    return docs


def summarize(docs: list[Document]) -> dict[str, int]:
    counts = {"total": len(docs), "kept": 0, "dropped_stub": 0, "dropped_duplicate": 0}
    for doc in docs:
        if doc.status == "kept":
            counts["kept"] += 1
        elif doc.drop_reason == "stub":
            counts["dropped_stub"] += 1
        elif doc.drop_reason and doc.drop_reason.startswith("duplicate:"):
            counts["dropped_duplicate"] += 1
    return counts
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_clean.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/clean.py tests/test_clean.py
git commit -m "feat: 清洗标记，保留 dropped 记录与 reason"
```

---

### Task 7: 落盘与路径冻结

**Files:**
- Create: `src/kb_init/emit.py`
- Test: `tests/test_emit.py`

**Interfaces:**
- Consumes: `kb_init.model.Document`
- Produces: `kb_init.emit.emit(docs: list[Document], out_dir: Path, wikilinks: bool = False) -> list[Document]` — 只写 `status == "kept"` 的文档到 `out_dir/knowledge/`，**为每篇设置 `out_relpath` 并返回**；`out_dir` 已存在且非空时抛 `FileExistsError`

**背景**：这是设计中被 Codex 抓到的顺序 bug 的修复点——**输出路径必须在生成任何证据引用之前冻结**。原设计把落盘放在渲染之后，导致报告里的证据链接指向尚未命名的文件。

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_emit.py
import pytest

from kb_init.emit import emit
from kb_init.model import Document


def _doc(doc_id: str, title: str, status: str = "kept") -> Document:
    return Document(
        doc_id=doc_id.ljust(16, "0"),
        source_relpath=f"deep/nested/{doc_id}.md",
        content_hash="c" * 16,
        title=title,
        body="正文" * 200,
        frontmatter={},
        created="2024-01-01",
        date_source="frontmatter",
        status=status,
    )


def test_only_kept_docs_are_written(tmp_path):
    docs = emit([_doc("a", "保留"), _doc("b", "丢弃", status="dropped")], tmp_path)
    written = list((tmp_path / "knowledge").glob("*.md"))
    assert len(written) == 1
    assert docs[0].out_relpath is not None
    assert docs[1].out_relpath is None


def test_out_relpath_is_frozen_and_file_exists(tmp_path):
    docs = emit([_doc("a", "标题")], tmp_path)
    target = tmp_path / docs[0].out_relpath
    assert target.exists()
    assert docs[0].out_relpath.startswith("knowledge/")


def test_paths_are_flattened_not_nested(tmp_path):
    """Notion 导出深达 11-15 层，必须拍平。"""
    docs = emit([_doc("a", "标题")], tmp_path)
    assert docs[0].out_relpath.count("/") == 1


def test_title_collision_gets_unique_path(tmp_path):
    docs = emit([_doc("a", "同名"), _doc("b", "同名")], tmp_path)
    assert docs[0].out_relpath != docs[1].out_relpath


def test_refuses_to_overwrite_existing_output(tmp_path):
    (tmp_path / "knowledge").mkdir(parents=True)
    (tmp_path / "knowledge" / "x.md").write_text("已有内容")
    with pytest.raises(FileExistsError):
        emit([_doc("a", "标题")], tmp_path)


def test_default_uses_standard_markdown_links(tmp_path):
    doc = _doc("a", "标题")
    doc.body = "见 [[另一篇]] 的说明"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[另一篇]]" not in written
    assert "[另一篇](另一篇.md)" in written


def test_wikilinks_flag_preserves_dialect(tmp_path):
    doc = _doc("a", "标题")
    doc.body = "见 [[另一篇]] 的说明"
    emit([doc], tmp_path, wikilinks=True)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[另一篇]]" in written


def test_frontmatter_carries_doc_id(tmp_path):
    docs = emit([_doc("a", "标题")], tmp_path)
    written = (tmp_path / docs[0].out_relpath).read_text(encoding="utf-8")
    assert docs[0].doc_id in written
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_emit.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.emit'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/emit.py
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_emit.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/emit.py tests/test_emit.py
git commit -m "feat: 落盘与路径冻结，默认标准 md 链接"
```

---

### Task 8: Manifest 与 corpus_hash

**Files:**
- Create: `src/kb_init/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `kb_init.model.Document`、`kb_init.clean.summarize`
- Produces:
  - `kb_init.manifest.SCHEMA_VERSION: int = 1`
  - `kb_init.manifest.compute_corpus_hash(docs: list[Document]) -> str` — 16 位 hex，仅依赖 doc_id 与 content_hash 的集合，与顺序无关
  - `kb_init.manifest.write_manifest(docs: list[Document], out_dir: Path, run_id: str, source: str) -> Path`
  - `kb_init.manifest.read_manifest(out_dir: Path) -> dict`

**背景**：R11（版本与证据链漂移）的落地点。后续 `compile` 会拿 manifest 里的 `corpus_hash` + `run_id` 做跨 run 编译的 fail-closed 判据。

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_manifest.py
from kb_init.manifest import (
    SCHEMA_VERSION, compute_corpus_hash, read_manifest, write_manifest,
)
from kb_init.model import Document


def _doc(doc_id: str, status: str = "kept") -> Document:
    return Document(
        doc_id=doc_id.ljust(16, "0"),
        source_relpath=f"{doc_id}.md",
        content_hash=doc_id.ljust(16, "f"),
        title="t",
        body="x" * 300,
        frontmatter={},
        status=status,
        out_relpath=f"knowledge/{doc_id}.md" if status == "kept" else None,
    )


def test_corpus_hash_is_order_independent():
    a, b = _doc("a"), _doc("b")
    assert compute_corpus_hash([a, b]) == compute_corpus_hash([b, a])


def test_corpus_hash_changes_with_content():
    a = _doc("a")
    modified = _doc("a")
    modified.content_hash = "9" * 16
    assert compute_corpus_hash([a]) != compute_corpus_hash([modified])


def test_manifest_roundtrip(tmp_path):
    docs = [_doc("a"), _doc("b", status="dropped")]
    docs[1].drop_reason = "stub"
    write_manifest(docs, tmp_path, run_id="run-1", source="/x/export")
    data = read_manifest(tmp_path)
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["run_id"] == "run-1"
    assert data["source"] == "/x/export"
    assert data["counts"]["total"] == 2
    assert data["counts"]["kept"] == 1
    assert len(data["documents"]) == 2


def test_dropped_documents_are_recorded_with_reason(tmp_path):
    dropped = _doc("b", status="dropped")
    dropped.drop_reason = "stub"
    write_manifest([dropped], tmp_path, run_id="r", source="s")
    entry = read_manifest(tmp_path)["documents"][0]
    assert entry["status"] == "dropped"
    assert entry["drop_reason"] == "stub"
    assert entry["out_relpath"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.manifest'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/manifest.py
"""可复现性台账。

记录 run_id / corpus_hash / schema_version 与每篇文档的完整状态，
让后续阶段能判断"这份 checklist 属不属于这次 run"，避免跨 run 编译。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kb_init import __version__
from kb_init.clean import summarize
from kb_init.model import Document

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"


def compute_corpus_hash(docs: list[Document]) -> str:
    parts = sorted(f"{d.doc_id}:{d.content_hash}" for d in docs)
    joined = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()[:16]


def write_manifest(
    docs: list[Document], out_dir: Path, run_id: str, source: str
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "run_id": run_id,
        "source": source,
        "corpus_hash": compute_corpus_hash(docs),
        "counts": summarize(docs),
        "documents": [
            {
                "doc_id": d.doc_id,
                "source_relpath": d.source_relpath,
                "content_hash": d.content_hash,
                "title": d.title,
                "created": d.created,
                "date_source": d.date_source,
                "status": d.status,
                "drop_reason": d.drop_reason,
                "out_relpath": d.out_relpath,
            }
            for d in docs
        ],
    }
    target = out_dir / MANIFEST_NAME
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def read_manifest(out_dir: Path) -> dict:
    return json.loads((Path(out_dir) / MANIFEST_NAME).read_text(encoding="utf-8"))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/manifest.py tests/test_manifest.py
git commit -m "feat: manifest 与 corpus_hash，为跨 run 校验打底"
```

---

### Task 9: 串联管线并接上 CLI

**Files:**
- Create: `src/kb_init/pipeline.py`
- Modify: `src/kb_init/cli.py`（替换 `main` 中 `return 0` 的占位分支）
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: 前八个任务的全部产出
- Produces: `kb_init.pipeline.run(source: Path, out_dir: Path, wikilinks: bool = False, run_id: str | None = None) -> dict` — 返回 manifest 的 `counts` 字典

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_e2e.py
import json
from pathlib import Path

from kb_init.pipeline import run


def _corpus(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "good1.md").write_text(
        "---\ntitle: 好文章\ncreated: 2023-04-01\n---\n\n" + "内容" * 200,
        encoding="utf-8",
    )
    (root / "good2.md").write_text("# 另一篇\n\n" + "别的内容" * 200, encoding="utf-8")
    (root / "stub.md").write_text("短", encoding="utf-8")
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "dup.md").write_text(
        "---\ntitle: 好文章\ncreated: 2023-04-01\n---\n\n" + "内容" * 200,
        encoding="utf-8",
    )
    return root


def test_end_to_end_counts(tmp_path):
    src = _corpus(tmp_path / "src")
    counts = run(src, tmp_path / "out", run_id="r1")
    assert counts["total"] == 4
    assert counts["kept"] == 2
    assert counts["dropped_stub"] == 1
    assert counts["dropped_duplicate"] == 1


def test_end_to_end_writes_only_kept_files(tmp_path):
    src = _corpus(tmp_path / "src")
    run(src, tmp_path / "out", run_id="r1")
    assert len(list((tmp_path / "out" / "knowledge").glob("*.md"))) == 2


def test_every_kept_doc_has_resolvable_out_path(tmp_path):
    """守卫测试：证据链接必须全部可解析——这是原设计顺序 bug 的回归测试。"""
    src = _corpus(tmp_path / "src")
    out = tmp_path / "out"
    run(src, out, run_id="r1")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    kept = [d for d in manifest["documents"] if d["status"] == "kept"]
    assert kept
    for entry in kept:
        assert entry["out_relpath"] is not None
        assert (out / entry["out_relpath"]).exists()


def test_dropped_docs_are_still_in_manifest(tmp_path):
    src = _corpus(tmp_path / "src")
    out = tmp_path / "out"
    run(src, out, run_id="r1")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["documents"]) == 4


def test_rerun_same_corpus_yields_same_corpus_hash(tmp_path):
    src = _corpus(tmp_path / "src")
    run(src, tmp_path / "out1", run_id="r1")
    run(src, tmp_path / "out2", run_id="r2")
    h1 = json.loads((tmp_path / "out1" / "manifest.json").read_text())["corpus_hash"]
    h2 = json.loads((tmp_path / "out2" / "manifest.json").read_text())["corpus_hash"]
    assert h1 == h2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kb_init.pipeline'`

- [ ] **Step 3: 写最小实现**

```python
# src/kb_init/pipeline.py
"""把七个阶段串成一条管线。

顺序不可调换：落盘（冻结路径）必须发生在任何证据引用生成之前。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from kb_init.clean import mark, summarize
from kb_init.dates import resolve_date
from kb_init.emit import emit
from kb_init.extract import walk_source
from kb_init.manifest import write_manifest
from kb_init.parse import parse_file


def run(
    source: Path,
    out_dir: Path,
    wikilinks: bool = False,
    run_id: str | None = None,
) -> dict:
    source = Path(source)
    out_dir = Path(out_dir)
    run_id = run_id or uuid.uuid4().hex[:12]

    files = walk_source(source)
    # source 是 zip 时，files 已被解压到临时目录，相对路径基准要从文件本身推
    base = source if source.is_dir() else _common_root(files)

    docs = []
    for path in files:
        doc = parse_file(path, base)
        doc.created, doc.date_source = resolve_date(doc, path)
        docs.append(doc)

    mark(docs)
    emit(docs, out_dir, wikilinks=wikilinks)
    write_manifest(docs, out_dir, run_id=run_id, source=str(source))
    return summarize(docs)


def _common_root(files: list[Path]) -> Path:
    if not files:
        return Path(".")
    parts = [f.parts for f in files]
    common = []
    for group in zip(*parts):
        if len(set(group)) == 1:
            common.append(group[0])
        else:
            break
    return Path(*common) if common else Path("/")
```

在 `src/kb_init/cli.py` 中，把 `main` 里的 `return 0` 替换为：

```python
    from kb_init.pipeline import run

    try:
        counts = run(args.source, args.out, wikilinks=args.wikilinks)
    except FileExistsError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    kept = counts["kept"]
    total = counts["total"]
    print(f"读入 {total} 篇，保留 {kept} 篇（留存 {kept / total:.0%}）" if total else "未找到 .md 文件")
    print(f"  空壳丢弃 {counts['dropped_stub']} 篇 / 重复丢弃 {counts['dropped_duplicate']} 篇")
    print(f"输出目录：{args.out}")
    return 0
```

同时在 `cli.py` 顶部保留已有 import，无需新增。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/ -v`
Expected: PASS（全部通过，41 passed）

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/pipeline.py src/kb_init/cli.py tests/test_e2e.py
git commit -m "feat: 串联核心管线并接上 CLI"
```

---

### Task 10: 在真实烂语料上验收

**Files:**
- Create: `tests/test_real_corpus.py`
- Modify: `README.md`（新建）

**Interfaces:**
- Consumes: `kb_init.pipeline.run`
- Produces: 无新接口。本任务的产出是**验收证据**。

**背景**：判据阈值必须在**烂语料**上校准。我们自己的 Wiki 是优等生样本（残桩率 0%），校准不出真实阈值。主校准集是 `~/Documents/notion-export/`（1925 篇 / 60% 空壳），副校准集是 `~/Documents/Obsidian Vault/Archive/Apple Notes`（620 篇 / 40% 空壳）。

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_real_corpus.py
"""在真实语料上的验收测试。语料不在时自动跳过，不阻塞 CI。"""
import os
from pathlib import Path

import pytest

from kb_init.pipeline import run

NOTION = Path(os.path.expanduser("~/Documents/notion-export"))
APPLE = Path(os.path.expanduser("~/Documents/Obsidian Vault/Archive/Apple Notes"))


@pytest.mark.skipif(not NOTION.exists(), reason="Notion 语料不在本机")
def test_notion_export_drops_majority_as_stubs(tmp_path):
    counts = run(NOTION, tmp_path / "out", run_id="acceptance-notion")
    assert counts["total"] > 1500
    stub_ratio = counts["dropped_stub"] / counts["total"]
    assert stub_ratio > 0.45, f"空壳率 {stub_ratio:.0%}，实测基线约 60%"


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_apple_notes_retention_near_baseline(tmp_path):
    counts = run(APPLE, tmp_path / "out", run_id="acceptance-apple")
    assert counts["total"] > 500
    retention = counts["kept"] / counts["total"]
    assert 0.25 < retention < 0.75, f"留存率 {retention:.0%}，历史人工基线 39%"


@pytest.mark.skipif(not APPLE.exists(), reason="Apple Notes 语料不在本机")
def test_no_unknown_date_explosion(tmp_path):
    """降级链若整体失效，unknown 会爆表——这是链条坏掉的哨兵。"""
    import json
    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-dates")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    unknown = sum(1 for d in docs if d["date_source"] == "unknown")
    assert unknown / len(docs) < 0.9, "降级链五级全落空，说明实现有问题"
```

- [ ] **Step 2: 运行测试确认失败或跳过**

Run: `uv run pytest tests/test_real_corpus.py -v`
Expected: 语料存在则 FAIL 或 PASS（首次跑很可能因阈值不符而 FAIL——**这正是校准的意义**）；语料不存在则 SKIPPED

- [ ] **Step 3: 按实测结果校准阈值**

跑一次拿到真实数字：

```bash
uv run kb-init ~/Documents/notion-export -o /tmp/kb-acceptance-notion
uv run kb-init "$HOME/Documents/Obsidian Vault/Archive/Apple Notes" -o /tmp/kb-acceptance-apple
```

把两次输出的实际数字填回 `tests/test_real_corpus.py` 的断言区间，并在 `README.md` 写下：

```markdown
# kb-init

把你攒了几年、自己都没再打开过的笔记导出，编译成一份干净的、你的 AI agent 能直接用的知识库。

## 安装与运行

需要先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。装好 uv 后一条命令运行，**无需自己安装 Python**：

```bash
uvx kb-init ~/Downloads/notion-export -o my-kb
```

> 首次运行会下载 Python 与依赖，可能需要几分钟。这不是"零安装"，是"零项目安装"。

## 它做了什么

在真实语料上的实测：

| 输入 | 读入 | 保留 |
|---|---|---|
| Notion 导出 | 1925 篇 | （填入实测） |
| Apple Notes | 620 篇 | （填入实测） |

被丢弃的记录**不会消失**——它们连同丢弃原因一起留在 `manifest.json` 里。

## 输出

```
my-kb/
├── knowledge/        干净的标准 Markdown（默认相对路径链接，不绑定 Obsidian）
└── manifest.json     每篇文档的完整状态、身份、日期来源与去向
```
```

- [ ] **Step 4: 重新运行全部测试**

Run: `uv run pytest tests/ -v`
Expected: PASS（真实语料测试通过或按语料缺失跳过）

- [ ] **Step 5: 提交**

```bash
git add tests/test_real_corpus.py README.md
git commit -m "test: 真实烂语料验收 + README"
```

---

## Self-Review

**1. 规格覆盖**

| DESIGN.md 要求 | 对应任务 |
|---|---|
| §4 [1] 归一 + 稳定 doc_id | Task 3、4 |
| §4 [2] 清洗 kept/dropped + reason | Task 6 |
| §4 [3] 落盘、路径冻结 | Task 7 |
| §4.3 IR 合同：doc_id / 标记不删 / 路径冻结 / manifest / 原子落盘不覆盖 | Task 3、6、7、8 |
| §5.1 新鲜度降级链五级、禁 mtime | Task 5 |
| §7 Python 3.12 + uv | Task 1 |
| §7 默认标准 md 链接 + `--wikilinks` | Task 1、7 |
| §7 输入为导出文件夹/zip | Task 2 |
| R13 输入安全（traversal / bomb / symlink / 超大） | Task 2 |
| §3 地面真值可复现（60% 空壳 / 39% 留存） | Task 10 |

**未覆盖项（属于 Plan 2，非缺口）**：§4.3 的 `doc_id → chunk_id` 分块映射、§5 洞察分层、§4.2 insights gate、§7 embedding 与脱敏、R12 隐私边界、R15 跨平台 CI。

**2. 占位符扫描**：无 TBD/TODO；每个代码步骤都有可运行代码；Task 10 Step 3 的"填入实测"是**要求执行者跑命令取真实数字**的动作，不是让实现者自由发挥的占位。

**3. 类型一致性**：`Document` 字段在 Task 3 定义后，Task 4/5/6/7/8/9 全部按同名字段使用；`resolve_date` 返回 `(str | None, str)` 与 Task 9 的 `doc.created, doc.date_source = ...` 解包一致；`summarize` 的四个键在 Task 6 定义、Task 8/9/10 一致引用。

**已修**：Task 9 初稿里 `run()` 有一个未使用的 `root` 变量并与 `base` 计算重复，已改为统一走 `_common_root`。
