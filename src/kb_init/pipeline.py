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

    **这个函数必须是全函数：任何输入都只返回枚举值，绝不抛异常。** 它跑在 except
    分支里，一旦自己抛出，原异常就会穿透出去把清洗产物一起带走——而它最容易抛的
    恰恰是 ImportError：早前它惰性导入 `EmbeddingError`，而触发它的第一现场
    可能正是 `embed.py` 导不进来（比如缺 numpy）。所以先判内建类型，
    再**在保护下**尝试识别自定义异常。
    """
    for exc_type, reason in _INDEX_FAILURE_REASONS:
        if isinstance(exc, exc_type):
            return reason
    try:
        from kb_init.embed import EmbeddingError

        if isinstance(exc, EmbeddingError):
            return "inference_failed"
    except Exception:
        pass
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


_INSIGHTS_FAILURE_REASONS = (
    (ImportError, "runtime_unavailable"),
    (OSError, "io_failed"),
    (ValueError, "contract_violation"),
)


def _classify_insights_failure(exc: Exception) -> str:
    """与 `_classify_index_failure` 同一条纪律：**必须是全函数**，任何输入都只
    返回枚举值。它跑在 except 分支里，自己抛出就会把已发布的产物一起带走。"""
    for exc_type, reason in _INSIGHTS_FAILURE_REASONS:
        if isinstance(exc, exc_type):
            return reason
    return "naming_failed"


def _run_insights_stage(
    staging: Path,
    docs: list,
    *,
    counts: dict,
    unresolved_links: list,
    index_status: str,
    corpus_provenance: str = "unknown",
) -> tuple[str, str | None]:
    """洞察阶段。失败必须在这里被吸收成状态——理由与索引阶段完全相同：
    rename 之前传播出去的任何异常都会让 finally 删掉 staging，清洗产物一并消失。

    **不读 manifest**：本阶段跑在 `write_manifest` 之前，manifest 还没落盘。
    需要的计数与断链由调用方把已经算好的值传进来。
    """
    if index_status == "skipped":
        return "skipped", "no_index"
    if index_status != "complete":
        return "skipped", "index_failed"

    try:
        from kb_init.index import read_index
        from kb_init.insights import (
            build_insight_set,
            cleanup_insight_files,
            insight_files_remain,
            write_insights,
        )
        from kb_init.insights_md import render_markdown

        # 写盘后**读回**，走公共读取器：这条路径能抓到序列化、映射与版本边界上的
        # 问题，而 2C/2D/2E 走的正是这条路。只测内存路径的话，三个下游第一次
        # 读文件时才会发现合同没兑现。
        # 唯一合法的 trust_manifest=False：本阶段跑在 write_manifest 之前
        index, _matrix = read_index(staging, trust_manifest=False)
        kept = [d for d in docs if d.status == "kept"]
        payload = build_insight_set(
            index,
            {"counts": counts, "unresolved_links": unresolved_links, "documents": []},
            {d.doc_id: d.body for d in kept},
            {d.doc_id: (d.title or "") for d in kept},
            corpus_provenance=corpus_provenance,
        )
        write_insights(staging, payload, render_markdown(payload))
        return "complete", None
    except Exception as exc:
        reason = _classify_insights_failure(exc)
        # 清理路径**绝不允许把异常放出去**。放出去就会穿到 run() 的 finally，
        # 把已经完成的清洗产物与索引一起删掉——那正是硬不变量 #2 禁止的事。
        #
        # 那半份洞察文件怎么办？让它留着，但把真相记在 manifest 里：
        # `insights_status=failed` + `insights_reason=io_failed`。**manifest 才是
        # 「哪些产物算数」的权威**，这也正是当初要有 status 字段的原因；
        # 下游（validate / compile）读不到配对的另一半自然会 fail closed。
        # 用「毁掉两份完好的产物」去换「删干净一份坏产物」，代价方向反了。
        try:
            from kb_init.insights import cleanup_insight_files, insight_files_remain

            cleanup_insight_files(staging)
            if insight_files_remain(staging):
                reason = "io_failed"
        except Exception:
            reason = "io_failed"
        return "failed", reason


def _subdivide_flagged_groups(
    doc_ids, matrix, assignments, method_dict, build_analysis, build_time_axis
) -> list[dict]:
    """2A′：把内聚度贴近 residual 基线的 group 细分成 analyses[1..]。

    **细分不回头修改 `analyses[0]` 的任何字段**——2A 合同要求同时保留「第一轮的
    residual」与「第二轮的 assigned」两套 disposition，编辑父分析会直接毁掉它。

    ⚠️ 这不等于「analyses[0] 与 2A 时期逐字节相同」：本轮给 `method.params` 新增了
    `cluster_selection_method` 与 `cohesion_lift_min`（参数必须随产物落盘）。
    不变的是**细分这个动作**不碰父分析，不是 schema 冻结。

    这个函数由 `_run_index_stage` 在它的 try 内部调用，因此异常照常向上抛，
    由那一层吸收成 index_status=failed 并回滚整个索引子事务。
    """
    import numpy as np

    from kb_init import subdivide as sd

    if not doc_ids:
        return []

    row_of = {d: matrix[i] for i, d in enumerate(doc_ids)}
    members_by_group: dict[str, list[str]] = {}
    for a in assignments:
        for m in a.memberships:
            members_by_group.setdefault(m.group_id, []).append(a.doc_id)
    residual_ids = [a.doc_id for a in assignments if a.disposition == "residual"]

    lifts = sd.group_lifts(members_by_group, residual_ids, row_of)
    flagged = sd.flagged_groups(lifts)
    if not flagged:
        return []

    baseline = sd.cohesion(
        np.vstack([row_of[d] for d in residual_ids if d in row_of])
    )
    extra: list[dict] = []
    for n, gid in enumerate(flagged, start=2):
        child_groups, child_assignments = sd.subdivide_group(
            gid, members_by_group[gid], row_of, baseline,
            min_cluster_size=5, min_samples=5,
        )
        child_method = dict(method_dict)
        child_method["params"] = {
            **method_dict["params"],
            "cluster_selection_method": "leaf",
        }
        extra.append(
            build_analysis(
                analysis_id=f"topics-{n:02d}",
                parent_analysis_id="topics-01",
                input_scope={
                    "kind": "parent_group",
                    "analysis_id": "topics-01",
                    "group_id": gid,
                },
                groups=child_groups,
                assignments=child_assignments,
                method=child_method,
                # 子分析不重算日期覆盖率：它是全局事实，记在根分析上就够了
                time_axis=build_time_axis(0, len(members_by_group[gid])),
            )
        )
    return extra


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
            build_analysis,
            build_index,
            build_time_axis,
            validate_index,
            write_index,
        )
        from kb_init.subdivide import COHESION_LIFT_MIN

        import numpy as np

        bodies = {d.doc_id: d.body for d in kept}
        # 空语料短路：既然没有任何文本要编码，就不该先把 90MB 模型加载起来、
        # 也不该让「写一份合法空索引」依赖 sklearn/onnxruntime 装没装好。
        if not kept:
            splitter_meta = {"name": "none", "max_tokens": 512, "fallback_used": False}
            model_name = getattr(embedder, "model_name", "none") if embedder else "none"
            chunks, doc_ids = [], []
            matrix = np.zeros((0, 0), dtype=np.float32)
            groups, assignments = [], []
        else:
            if splitter is None:
                from kb_init.embed import build_splitter

                splitter, splitter_meta = build_splitter()
            else:
                splitter_meta = {
                    "name": "injected", "max_tokens": 512, "fallback_used": False
                }

            if embedder is None:
                from kb_init.embed import DEFAULT_MODEL, FastEmbedEmbedder

                embedder = FastEmbedEmbedder()
                model_name = DEFAULT_MODEL
            else:
                model_name = getattr(embedder, "model_name", "injected")

            chunks = chunk_documents([(d.doc_id, d.body) for d in kept], splitter)
            vectors = list(
                embedder.embed([bodies[c.doc_id][c.start:c.end] for c in chunks])
            )
            doc_ids, matrix = pool_chunk_vectors(chunks, vectors)
            # 全部文档都切不出块时同样不必进聚类
            groups, assignments = (
                cluster_documents(doc_ids, matrix) if doc_ids else ([], [])
            )

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
        method_dict = {
            "family": "density",
            "name": "hdbscan",
            "model": model_name,
            "model_revision": getattr(embedder, "revision", ""),
            "params": {
                "min_cluster_size": 5,
                "min_samples": 5,
                "metric": "euclidean",
                # 参数不落盘等于产物隐瞒了自己是怎么来的
                "cluster_selection_method": "eom",
                "cohesion_lift_min": COHESION_LIFT_MIN,
            },
            "seed": 0,
            "splitter": splitter_meta,
            "pooling": "mean_l2",
            "score_kind": "density_membership",
            "score_direction": "higher_better",
            "decision_threshold": None,
        }

        extra_analyses = _subdivide_flagged_groups(
            doc_ids, matrix, assignments, method_dict, build_analysis, build_time_axis
        )

        index = build_index(
            run_id=run_id,
            corpus_hash=corpus_hash,
            chunks=chunks,
            groups=groups,
            assignments=assignments,
            method=method_dict,
            extra_analyses=extra_analyses,
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
                # 曾经在这里 `raise OSError`，理由是「半个索引比整次失败更糟」。
                # 那条推理漏了一步：raise 会穿到 run() 的 finally，把**清洗产物**
                # 也一起删掉——而清洗产物是完好的，用户要的正是它。
                # 半个索引由 manifest 兜住：index_status=failed 就是「别信这些文件」，
                # 这也正是当初要有 status 字段的原因。清理路径绝不放异常出去。
                reason = "io_failed"
        except Exception:
            reason = "io_failed"
        return "failed", reason


def run(
    source: Path,
    out_dir: Path,
    wikilinks: bool = False,
    run_id: str | None = None,
    no_index: bool = False,
    embedder=None,
    splitter=None,
    corpus_provenance: str = "unknown",
) -> dict:
    source = Path(source)
    out_dir = Path(out_dir)
    run_id = run_id or uuid.uuid4().hex[:12]

    collisions: list[dict] = []
    scratch: list[Path] = []            # zip 解压临时目录，见下方 _discard
    staging: Path | None = None
    published = False

    def _discard_strict() -> None:
        """commit **之前**的严格清理：删完必须复核路径确实不在了。

        用户笔记的明文躺在这些临时目录里。`ignore_errors=True` 删不掉也当作删掉，
        然后照常发布产物——那就等于一边承诺"全程本地不留痕"，一边把明文留在盘上。
        删不掉就在 rename 之前中止，宁可整次失败。
        """
        for path in list(scratch):
            shutil.rmtree(path, ignore_errors=True)
            if path.exists():
                raise OSError(f"临时解压目录无法删除，拒绝在明文残留的情况下发布：{path}")
            scratch.remove(path)

    def _discard_best_effort() -> None:
        """异常路径上的兜底清理。**永不抛异常**——此时已经在处理别的失败了。"""
        for path in list(scratch):
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

        insights_status, insights_reason = _run_insights_stage(
            staging, docs,
            counts=summarize(docs),
            unresolved_links=result.unresolved_links,
            index_status=index_status,
            corpus_provenance=corpus_provenance,
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
            insights_status=insights_status,
            insights_reason=insights_reason,
        )

        # 返回值在 commit **之前**算好。放在 rename 之后算，一旦 summarize 抛错
        # 就会出现"产物已发布但命令报错"——那正是失败原子性要排除的现象。
        summary = summarize(docs)
        summary["index_status"] = index_status
        summary["index_reason"] = index_reason
        summary["insights_status"] = insights_status
        summary["insights_reason"] = insights_reason

        # 临时目录在 commit 前严格清掉：放到 return 时清理，一旦清理失败就会在
        # 产物已发布之后抛异常，制造"命令报错但产物已发布"；而删不干净又照常发布，
        # 等于把用户笔记的明文留在盘上。两者都不接受，所以在这里删并复核。
        _discard_strict()

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
        _discard_best_effort()
