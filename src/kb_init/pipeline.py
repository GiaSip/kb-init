"""把七个阶段串成一条管线。

顺序不可调换：落盘（冻结路径）必须发生在任何证据引用生成之前。

临时目录用显式 try/finally 管理而非 ExitStack：ExitStack 的清理发生在 run() 返回时，
也就是 commit 点之后，清理失败会制造"命令报错但产物已发布"。改为在 rename 之前主动清掉，
finally 只兜异常路径——两条路径都保证用户笔记明文不会永久留盘。
"""
from __future__ import annotations

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


_INDEX_FAILURE_REASONS = (
    # (异常类型, 稳定 reason_code)。顺序即优先级。
    (ImportError, "runtime_unavailable"),
    (FileNotFoundError, "model_unavailable"),
    (OSError, "io_failed"),
    (ValueError, "contract_violation"),
)


def _classify_index_failure(exc: Exception) -> str:
    """把异常映射成**稳定**的 reason_code。

    早前直接写 `type(exc).__name__`：那是实现细节，换个库、换个 Python 版本就漂移，
    而 manifest 里的 reason 是要给脚本判断用的。
    """
    from kb_init.embed import EmbeddingError

    if isinstance(exc, EmbeddingError):
        return "inference_failed"
    for exc_type, reason in _INDEX_FAILURE_REASONS:
        if isinstance(exc, exc_type):
            return reason
    return "inference_failed"


def _versions(embedder=None) -> dict:
    """可复现性的版本边界：同样的输入只在同样的依赖版本下才保证同样的输出。

    聚类结果会随 sklearn / numpy / scipy 版本变化，embedding 会随推理运行时与
    模型文件变化——不记下来，"可复现"就是一句无法验证的断言。

    `embedder_adapter` 取自实际使用的 embedder：注入假实现时仍写 fastembed，
    等于让产物撒谎。
    """
    import sys

    from kb_init import __version__

    def _ver(module_name: str) -> str:
        try:
            from importlib.metadata import version

            return version(module_name)
        except Exception:
            return "unknown"

    adapter = getattr(embedder, "provenance", None)
    if adapter is None:
        if embedder is None:
            from kb_init.embed import _fastembed_version

            adapter = _fastembed_version()
        else:
            adapter = f"injected:{type(embedder).__name__}"

    return {
        "kb_init": __version__,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "numpy": _ver("numpy"),
        "scipy": _ver("scipy"),
        "sklearn": _ver("scikit-learn"),
        "onnxruntime": _ver("onnxruntime"),
        "embedder_adapter": adapter,
    }


def _run_index_stage(
    staging: Path, docs: list, embedder, splitter, *, run_id: str, corpus_hash: str
) -> tuple[str, str | None]:
    """在 staging 内构建索引，返回 (status, reason)。

    **失败必须在这里被吸收成状态。** run() 的 finally 会在未发布时 rmtree(staging)：
    任何在 rename 之前传播出去的异常都会连清洗产物一起删掉——那样 CLI 再返回
    退出码 5 就是在撒谎，因为产物根本不存在。

    只接 `Exception`：`KeyboardInterrupt` / `SystemExit` 是 BaseException，必须透传，
    不能被伪装成"部分成功"。

    **索引专属的 import 必须写在 try 里面。** 曾经把它们放在函数开头，结果平台缺
    sklearn / onnxruntime wheel 时（R15 点名的风险）ImportError 直接穿透出去，
    staging 连同清洗产物一起被删——正是退出码 5 承诺不会发生的事。
    """
    kept = [d for d in docs if d.status == "kept"]

    try:
        from kb_init.chunk import chunk_documents
        from kb_init.cluster import Assignment, cluster_documents
        from kb_init.embed import pool_chunk_vectors
        from kb_init.index import (
            build_index,
            build_time_axis,
            validate_index,
            write_index,
        )

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
        if not doc_ids:
            groups, assignments = [], []

        # 切不出块的文档（正文为空白）拿不到向量，必须显式补一条 residual，
        # 否则「每个 kept doc 恰有一条 assignment」这条合同会被悄悄破坏。
        missing = sorted({d.doc_id for d in kept} - set(doc_ids))
        assignments = list(assignments) + [
            Assignment(d, "residual", (), "empty_document") for d in missing
        ]

        dated_by_doc = {
            d.doc_id: d.created
            for d in kept
            if d.date_source not in ("unknown", "unresolved") and d.created
        }
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
            time_axis=build_time_axis(
                len(dated_by_doc),
                len(kept),
                dates_by_doc=dated_by_doc,
                groups=groups,
                assignments=assignments,
            ),
            versions=_versions(embedder),
            vector_doc_ids=doc_ids,
        )
        validate_index(index, [d.doc_id for d in kept], matrix, bodies)
        write_index(staging, index, matrix)
        return "complete", None
    except Exception as exc:
        reason = _classify_index_failure(exc)
        try:
            from kb_init.index import cleanup_index_files, index_files_remain

            cleanup_index_files(staging)
            if index_files_remain(staging):
                # 回滚没干净就不能声称"只是索引没做成"——半个索引会让 2B 读到
                # 一份说谎的产物，那比整次失败更糟。
                raise OSError("索引半成品无法清除")
        except ImportError:
            pass                        # index 模块本身没导入成功，自然没有半成品
        return "failed", reason


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
    scratch: list[Path] = []            # zip 解压临时目录，见下方 _discard
    staging: Path | None = None
    published = False

    def _discard() -> None:
        """清理临时目录。**永不抛异常**——它会在 commit 点前后都被调用，
        任何一次抛出都会制造"产物已发布但命令报错"。"""
        for path in scratch:
            shutil.rmtree(path, ignore_errors=True)
        scratch.clear()

    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            # 不用 TemporaryDirectory + ExitStack：它的清理发生在 run() 返回时，
            # 也就是 commit 点之后；清理失败就会在产物已发布后抛异常。
            # 改为手动管理，在 rename 之前主动清掉。
            tmp_dir = Path(tempfile.mkdtemp(prefix="kb-init-"))
            scratch.append(tmp_dir)
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

        # 返回值在 commit **之前**算好。放在 rename 之后算，一旦 summarize 抛错
        # 就会出现"产物已发布但命令报错"——那正是失败原子性要排除的现象。
        summary = summarize(docs)
        summary["index_status"] = index_status
        summary["index_reason"] = index_reason

        # 临时目录在 commit 前主动清掉：放到 return 时清理，一旦清理失败就会在
        # 产物已发布之后抛异常，制造"命令报错但产物已发布"。
        _discard()

        # 发布：一次 rename。out_dir 若已存在（空目录）先移走，
        # 使 rename 目标不存在——同一文件系统内 rename 是原子的。
        if out_dir.exists():
            out_dir.rmdir()             # 上面已确保它是空的
        staging.rename(out_dir)         # ← commit 点，此后不做任何事
        published = True
        return summary
    finally:
        # staging 只在**未发布**时清理。判据用"路径是否还在"而不是只看 published：
        # rename 成功与置位之间若被 Ctrl-C 打断，staging 路径已经不存在，
        # rmtree 也就不会误删已发布的产物。
        if not published and staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        _discard()
