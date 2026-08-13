"""把七个阶段串成一条管线。

顺序不可调换：落盘（冻结路径）必须发生在任何证据引用生成之前。

zip 临时目录通过 contextlib.ExitStack + tempfile.TemporaryDirectory 管理，
保证在 run() 返回前（含异常路径）一定被清理，防止用户笔记明文永久留盘。
"""
from __future__ import annotations

import contextlib
import tempfile
import uuid
from pathlib import Path

from kb_init.clean import mark, summarize
from kb_init.dates import resolve_date
from kb_init.emit import emit
from kb_init.extract import safe_extract, walk_source
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

    with contextlib.ExitStack() as stack:
        if source.is_file() and source.suffix.lower() == ".zip":
            # ExitStack 确保 TemporaryDirectory 在 run() 返回前被删除，
            # 无论正常返回还是异常退出——防止用户笔记明文留在临时目录。
            tmp_dir = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="kb-init-"))
            )
            base = safe_extract(source, tmp_dir)
            files = walk_source(base)
        else:
            base = source
            files = walk_source(source)

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
    """推算一组文件路径的公共父目录（zip 解压场景备用工具）。

    原始实现用完整路径部件（f.parts）做前缀计算，在「zip 仅含单个文件」时
    会把文件本身当作基准（source_relpath='.'），而非其父目录。

    已修复：改用父目录部件（f.parent.parts）。
    - 单文件 /tmp/x/notes.md → /tmp/x  ✓
    - 同级多文件 /tmp/x/a.md + /tmp/x/b.md → /tmp/x  ✓
    - 跨目录 /tmp/x/sub1/a.md + /tmp/x/sub2/b.md → /tmp/x  ✓

    注意：run() 内部已通过 ExitStack + TemporaryDirectory 显式管理 zip 临时
    目录，_common_root 作为备用工具保留，不在主管线调用路径上。
    """
    if not files:
        return Path(".")
    parts = [f.parent.parts for f in files]
    common: list[str] = []
    for group in zip(*parts):
        if len(set(group)) == 1:
            common.append(group[0])
        else:
            break
    return Path(*common) if common else Path("/")
