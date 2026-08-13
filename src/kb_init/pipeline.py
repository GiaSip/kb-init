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

    collisions: list[dict] = []

    with contextlib.ExitStack() as stack:
        if source.is_file() and source.suffix.lower() == ".zip":
            # ExitStack 确保 TemporaryDirectory 在 run() 返回前被删除，
            # 无论正常返回还是异常退出——防止用户笔记明文留在临时目录。
            tmp_dir = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="kb-init-"))
            )
            base = safe_extract(source, tmp_dir)
            files = walk_source(base, collisions=collisions)
        else:
            base = source
            files = walk_source(source, collisions=collisions)

        docs = []
        for path in files:
            doc = parse_file(path, base)
            doc.created, doc.date_source = resolve_date(doc, path)
            docs.append(doc)

        mark(docs)

        # 整次运行原子：全部产物先落 staging，成功后一次性发布。
        # 逐篇原子（写 .tmp 再 replace）不够——第 N 篇失败时前 N-1 篇
        # 已是正式文件而 manifest 尚未写入，重跑又被 knowledge/ 非空拒绝，
        # 用户会卡在一个既不完整也无法重来的状态。
        if (out_dir / "knowledge").exists() and any(
            (out_dir / "knowledge").iterdir()
        ):
            raise FileExistsError(
                f"输出目录已存在内容，拒绝覆盖：{out_dir / 'knowledge'}。"
                "请换一个 --out 目录。"
            )
        out_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(prefix=".kb-init-staging-", dir=out_dir)
            )
        )

        result = emit(docs, staging, wikilinks=wikilinks)
        write_manifest(
            docs,
            staging,
            run_id=run_id,
            source=str(source),
            unresolved_links=result.unresolved_links,
            skipped_inputs=collisions,
        )

        for item in sorted(staging.iterdir()):      # 发布
            item.rename(out_dir / item.name)

        return summarize(docs)
