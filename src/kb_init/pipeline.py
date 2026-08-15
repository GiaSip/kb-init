"""把七个阶段串成一条管线。

顺序不可调换：落盘（冻结路径）必须发生在任何证据引用生成之前。

zip 临时目录通过 contextlib.ExitStack + tempfile.TemporaryDirectory 管理，
保证在 run() 返回前（含异常路径）一定被清理，防止用户笔记明文永久留盘。
"""
from __future__ import annotations

import contextlib
import shutil
import tempfile
import uuid
from pathlib import Path

from kb_init.clean import mark, summarize
from kb_init.dates import resolve_date
from kb_init.emit import emit
from kb_init.extract import safe_extract, walk_source
from kb_init.manifest import compute_corpus_hash, write_manifest
from kb_init.parse import parse_file


def _versions() -> dict:
    """可复现性的版本边界：同样的输入只在同样的依赖版本下才保证同样的输出。

    聚类结果会随 sklearn 版本变化，embedding 会随 fastembed / 模型文件变化——
    不记下来，"可复现"就是一句无法验证的断言。
    """
    from kb_init import __version__
    from kb_init.embed import _fastembed_version

    try:
        import sklearn

        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = "unknown"
    return {
        "kb_init": __version__,
        "sklearn": sklearn_version,
        "embedder_adapter": _fastembed_version(),
    }


def _run_index_stage(
    staging: Path, docs: list, embedder, splitter, *, run_id: str, corpus_hash: str
) -> tuple[str, str | None]:
    """在 staging 内构建索引，返回 (status, reason)。

    **失败必须在这里被吸收成状态。** run() 的 ExitStack 注册了
    `published or rmtree(staging)`：任何在 rename 之前传播出去的异常都会连清洗产物
    一起删掉——那样 CLI 再返回退出码 5 就是在撒谎，因为产物根本不存在。

    只接 `Exception`：`KeyboardInterrupt` / `SystemExit` 是 BaseException，必须透传，
    不能被伪装成"部分成功"。
    """
    from kb_init.chunk import chunk_documents
    from kb_init.cluster import Assignment, cluster_documents
    from kb_init.embed import pool_chunk_vectors
    from kb_init.index import build_index, build_time_axis, validate_index, write_index

    kept = [d for d in docs if d.status == "kept"]
    if not kept:
        return "complete", None

    try:
        if splitter is None:
            from kb_init.embed import build_splitter

            splitter, splitter_meta = build_splitter()
        else:
            splitter_meta = {"name": "injected", "max_tokens": 512, "fallback_used": False}

        if embedder is None:
            from kb_init.embed import DEFAULT_MODEL, FastEmbedEmbedder

            embedder = FastEmbedEmbedder()
            model_name = DEFAULT_MODEL
        else:
            model_name = getattr(embedder, "model_name", "injected")

        bodies = {d.doc_id: d.body for d in kept}
        chunks = chunk_documents([(d.doc_id, d.body) for d in kept], splitter)
        vectors = list(embedder.embed([bodies[c.doc_id][c.start:c.end] for c in chunks]))
        doc_ids, matrix = pool_chunk_vectors(chunks, vectors)

        groups, assignments = cluster_documents(doc_ids, matrix)

        # 切不出块的文档（正文为空白）拿不到向量，必须显式补一条 residual，
        # 否则「每个 kept doc 恰有一条 assignment」这条合同会被悄悄破坏。
        missing = sorted({d.doc_id for d in kept} - set(doc_ids))
        assignments = list(assignments) + [
            Assignment(d, "residual", (), "empty_document") for d in missing
        ]

        dated = sum(1 for d in kept if d.date_source not in ("unknown", "unresolved"))
        index = build_index(
            run_id=run_id,
            corpus_hash=corpus_hash,
            chunks=chunks,
            groups=groups,
            assignments=assignments,
            method={
                "family": "density",
                "name": "hdbscan",
                "model": model_name,
                "model_revision": getattr(embedder, "revision", ""),
                "params": {
                    "min_cluster_size": 5,
                    "min_samples": 5,
                    "metric": "euclidean",
                },
                "seed": 0,
                "splitter": splitter_meta,
                "pooling": "mean_l2",
                "score_kind": "density_membership",
                "score_direction": "higher_better",
                "decision_threshold": None,
            },
            time_axis=build_time_axis(dated, len(kept)),
            versions=_versions(),
        )
        validate_index(index, [d.doc_id for d in kept])
        write_index(staging, index, matrix)
        return "complete", None
    except Exception as exc:
        from kb_init.index import INDEX_FILES

        for name in INDEX_FILES:
            (staging / name).unlink(missing_ok=True)
        return "failed", type(exc).__name__


def run(
    source: Path,
    out_dir: Path,
    wikilinks: bool = False,
    run_id: str | None = None,
    no_index: bool = False,
    embedder=None,
    splitter=None,
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
        # 拒绝任何既有内容——不只是 knowledge/。既有 manifest.json 在 POSIX
        # 上会被静默覆盖，既有同名目录还会让发布失败。
        # lexists 而非 exists：断链 symlink 在 exists() 下返回 False，
        # 会让后续 rename 覆盖掉这个既有目录项。
        if out_dir.is_symlink() or (out_dir.exists() and not out_dir.is_dir()):
            raise FileExistsError(
                f"输出路径已存在且不是空目录：{out_dir}。请换一个 --out 目录。"
            )
        if out_dir.exists() and any(out_dir.iterdir()):
            raise FileExistsError(
                f"输出目录已存在内容，拒绝覆盖：{out_dir}。请换一个 --out 目录。"
            )
        # staging 建在**父目录**下，这样发布是「一次目录级 rename」而非
        # 逐个产物 rename。分两次 rename 时第二次失败会留下半成品，
        # 那就不叫整次运行原子了。
        parent = out_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        # 手动管理而非 TemporaryDirectory：发布是把 staging 本身 rename 走，
        # 之后任何「重建目录好让自动清理无害」的补救都发生在 commit 点之后——
        # 那一步若失败就会出现「命令报错但产物已发布」，破坏失败原子性。
        staging = Path(tempfile.mkdtemp(prefix=".kb-init-staging-", dir=parent))
        published = False
        stack.callback(
            lambda: None if published else shutil.rmtree(staging, ignore_errors=True)
        )

        result = emit(docs, staging, wikilinks=wikilinks)

        corpus_hash = compute_corpus_hash(docs)
        if no_index:
            index_status, index_reason = "skipped", None
        else:
            index_status, index_reason = _run_index_stage(
                staging, docs, embedder, splitter,
                run_id=run_id, corpus_hash=corpus_hash,
            )

        write_manifest(
            docs,
            staging,
            run_id=run_id,
            source=str(source),
            unresolved_links=result.unresolved_links,
            skipped_inputs=collisions,
            index_status=index_status,
            index_reason=index_reason,
        )

        # 发布：一次 rename。out_dir 若已存在（空目录）先移走，
        # 使 rename 目标不存在——同一文件系统内 rename 是原子的。
        if out_dir.exists():
            out_dir.rmdir()             # 上面已确保它是空的
        staging.rename(out_dir)         # ← commit 点，此后不做任何可能失败的事
        published = True

        # commit 点之后只做纯计算：把索引状态并进返回值，由调用方映射退出码。
        # 绝不在这里 raise——那会造成"命令报错但产物已发布"。
        summary = summarize(docs)
        summary["index_status"] = index_status
        summary["index_reason"] = index_reason
        return summary
