"""组装 index.json 并落盘。本层**唯一**写盘的模块。

`analyses` 从第一天就是数组：将来 residual 二次微聚类需要同时保留「第一轮 residual」
与「第二轮 micro assigned」两套 disposition，单顶层结构表达不了，等到那时再改
就是破坏性迁移。现在多写一层数组是零成本。
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

import numpy as np

from kb_init.chunk import Chunk
from kb_init.cluster import Assignment, Group

SCHEMA_VERSION = "0.1"
TIME_AXIS_THRESHOLD = 0.30
ANALYSIS_ID = "topics-01"

INDEX_FILES = ("index.json", "index-vectors.npy")


def build_time_axis(
    dated_docs: int,
    total_docs: int,
    threshold: float = TIME_AXIS_THRESHOLD,
    *,
    dates_by_doc: dict[str, str] | None = None,
    groups: Sequence[Group] = (),
    assignments: Sequence[Assignment] = (),
) -> dict:
    """只报事实，不做判断：是否变成一条洞察由 2B 决定。

    阈值取在实测的两档语料之间（导出类 5–6%，已维护类 43%），中间是空的，
    0.10–0.40 的任何取值在现有证据下行为相同。

    `per_group` **仅在 available 为真时才计算**：覆盖率不够时算出来的每簇时间跨度
    只会诱使下游拿 5% 的样本当整体讲，不如根本不给。
    """
    coverage = (dated_docs / total_docs) if total_docs else 0.0
    available = coverage >= threshold
    per_group = None
    if available and dates_by_doc:
        per_group = []
        members_of: dict[str, list[str]] = {g.group_id: [] for g in groups}
        for a in assignments:
            for m in a.memberships:
                if m.group_id in members_of:
                    members_of[m.group_id].append(a.doc_id)
        for group_id, doc_ids in members_of.items():
            dates = sorted(d for d in (dates_by_doc.get(x) for x in doc_ids) if d)
            per_group.append(
                {
                    "group_id": group_id,
                    "dated_docs": len(dates),
                    "total_docs": len(doc_ids),
                    "earliest": dates[0] if dates else None,
                    "latest": dates[-1] if dates else None,
                }
            )
    return {
        "dated_docs": dated_docs,
        "total_docs": total_docs,
        "coverage": round(coverage, 6),
        "threshold": threshold,
        "available": available,
        "per_group": per_group,
    }


def build_analysis(
    *,
    analysis_id: str,
    parent_analysis_id: str | None,
    input_scope: dict,
    groups: Sequence[Group],
    assignments: Sequence[Assignment],
    method: dict,
    time_axis: dict,
) -> dict:
    """构造一项 analysis。根分析与子分析走同一个构造器——两处各拼一份
    结构，迟早会长出两套不一样的形状，而形状不一致不会有任何症状。
    """
    dispositions = [a.disposition for a in assignments]
    return {
        "analysis_id": analysis_id,
        "parent_analysis_id": parent_analysis_id,
        "input_scope": input_scope,
        "method": method,
        "groups": [
            {
                "group_id": g.group_id,
                "kind": g.kind,
                "member_counts": g.member_counts,
                "representatives": g.representatives,
                "prototype": g.prototype,
            }
            for g in groups
        ],
        "assignments": [
            {
                "doc_id": a.doc_id,
                "disposition": a.disposition,
                "memberships": [asdict(m) for m in a.memberships],
                "reason_code": a.reason_code,
            }
            for a in assignments
        ],
        # coverage 必须由 assignments 派生。独立计数迟早会与 assignments
        # 漂移，而漂移后没有任何测试会发现。
        "coverage": {
            "assigned": dispositions.count("assigned"),
            "ambiguous": dispositions.count("ambiguous"),
            "residual": dispositions.count("residual"),
        },
        "time_axis": time_axis,
    }


def build_index(
    *,
    run_id: str,
    corpus_hash: str,
    chunks: Sequence[Chunk],
    groups: Sequence[Group],
    assignments: Sequence[Assignment],
    method: dict,
    time_axis: dict,
    versions: dict,
    vector_doc_ids: Sequence[str],
    extra_analyses: Sequence[dict] = (),
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "corpus_hash": corpus_hash,
        "versions": versions,
        # 向量矩阵的行 → doc_id 的**显式**映射。不用「按 doc_id 升序」这种约定：
        # 切不出块的文档有 assignment 却没有向量行，两者数量本就可以不等，
        # 靠约定推断行归属迟早会错位，而错位不会有任何症状。
        "vector_doc_ids": list(vector_doc_ids),
        "chunks": [asdict(c) for c in chunks],
        "analyses": [
            build_analysis(
                analysis_id=ANALYSIS_ID,
                parent_analysis_id=None,
                input_scope={"kind": "all_kept_docs"},
                groups=groups,
                assignments=assignments,
                method=method,
                time_axis=time_axis,
            ),
            *extra_analyses,
        ],
    }


_DISPOSITIONS = {"assigned", "ambiguous", "residual"}
_ROLES = {"hard", "core", "halo", "micro", "member"}


def _validate_analysis(analysis: dict, expected_doc_ids: Sequence[str]) -> None:
    """单项 analysis 的合同自检。

    校验范围刻意覆盖到「结构合法但语义在撒谎」的形态——例如 residual 却带着
    membership、representative 不属于本簇——这类问题不会让任何东西崩溃，
    只会让 2B 悄悄算错。
    """
    assignments = analysis["assignments"]

    assigned_ids = [a["doc_id"] for a in assignments]
    if len(set(assigned_ids)) != len(assigned_ids):
        raise ValueError("assignment 出现重复 doc_id")
    if sorted(assigned_ids) != sorted(expected_doc_ids):
        raise ValueError("每个 kept 文档必须恰有一条 assignment")

    known_groups = {g["group_id"] for g in analysis["groups"]}
    if len(known_groups) != len(analysis["groups"]):
        raise ValueError("group_id 重复")

    for a in assignments:
        if a["disposition"] not in _DISPOSITIONS:
            raise ValueError(f"非法 disposition：{a['disposition']}")
        seen_groups = set()
        for m in a["memberships"]:
            if m["group_id"] not in known_groups:
                raise ValueError(f"membership 指向不存在的 group：{m['group_id']}")
            if m["group_id"] in seen_groups:
                raise ValueError(f"{a['doc_id']} 对同一 group 有重复 membership")
            seen_groups.add(m["group_id"])
            if m["role"] not in _ROLES:
                raise ValueError(f"非法 role：{m['role']}")
            score = m["score"]
            if not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError(f"score 必须是有限数：{score}")
        # 结构合法但语义撒谎的两种形态
        if a["disposition"] == "residual" and a["memberships"]:
            raise ValueError(f"{a['doc_id']} 标为 residual 却带着 membership")
        if a["disposition"] == "assigned" and not a["memberships"]:
            raise ValueError(f"{a['doc_id']} 标为 assigned 却没有任何 membership")

    counted = {"assigned": 0, "ambiguous": 0, "residual": 0}
    for a in assignments:
        counted[a["disposition"]] += 1
    if counted != analysis["coverage"]:
        raise ValueError("coverage 与 assignments 不自洽")

    for g in analysis["groups"]:
        members_by_role: dict[str, set[str]] = {}
        for a in assignments:
            for m in a["memberships"]:
                if m["group_id"] == g["group_id"]:
                    members_by_role.setdefault(m["role"], set()).add(a["doc_id"])
        counts = g["member_counts"]
        for role in ("core", "halo", "micro"):
            if len(members_by_role.get(role, ())) != counts.get(role, 0):
                raise ValueError(f"{g['group_id']} 的 {role} 计数与 memberships 不符")
        all_members = set().union(*members_by_role.values()) if members_by_role else set()
        if counts.get("total_docs") != len(all_members):
            raise ValueError(f"{g['group_id']} 的 total_docs 与实际成员数不符")
        for rep in g["representatives"]:
            if rep["doc_id"] not in all_members:
                raise ValueError(
                    f"{g['group_id']} 的代表 {rep['doc_id']} 不是本簇成员"
                )


def validate_index(
    index: dict,
    kept_doc_ids: Sequence[str],
    matrix: "np.ndarray | None" = None,
    bodies: dict[str, str] | None = None,
) -> None:
    """合同自检。宁可在写盘前炸，也不要产出一份下游读不懂、或会说谎的索引。

    根分析必须覆盖全部 kept 文档；子分析（2A′ 的过大簇细分）必须**恰好**覆盖
    它所指向的父 group 的成员集合——多一篇少一篇都会让「呈现级 group」这个
    派生量算错，而算错没有任何症状。
    """
    analyses = index["analyses"]
    analysis_ids = [a["analysis_id"] for a in analyses]
    if len(set(analysis_ids)) != len(analysis_ids):
        raise ValueError("analysis_id 重复")

    root = analyses[0]
    _validate_analysis(root, sorted(kept_doc_ids))

    members_by_group: dict[tuple[str, str], set[str]] = {}
    for a in analyses:
        for asg in a["assignments"]:
            for m in asg["memberships"]:
                members_by_group.setdefault(
                    (a["analysis_id"], m["group_id"]), set()
                ).add(asg["doc_id"])

    seen_scopes: set[tuple[str, str]] = set()
    for position, child in enumerate(analyses[1:], start=1):
        scope = child["input_scope"]
        if scope.get("kind") != "parent_group":
            raise ValueError(f"子分析的 input_scope 必须是 parent_group：{scope}")
        key = (scope["analysis_id"], scope["group_id"])
        # 下面四条都不会让任何东西崩溃，只会让「呈现级 group」这个派生量
        # 少算或重复算——而算错没有任何症状。
        if child["parent_analysis_id"] != scope["analysis_id"]:
            raise ValueError(
                f"子分析 {child['analysis_id']} 的 parent_analysis_id 与 "
                f"input_scope.analysis_id 不一致"
            )
        if scope["analysis_id"] == child["analysis_id"]:
            raise ValueError(f"子分析 {child['analysis_id']} 指向自己")
        if scope["analysis_id"] not in analysis_ids[:position]:
            # 只能指向**排在自己前面**的分析：这一条同时排除了循环引用与前向引用
            raise ValueError(
                f"子分析 {child['analysis_id']} 指向的父分析未排在它之前：{key}"
            )
        if key in seen_scopes:
            raise ValueError(f"同一个父 group 被细分了两次：{key}")
        seen_scopes.add(key)
        if key not in members_by_group:
            raise ValueError(f"子分析指向不存在的父 group：{key}")
        expected = sorted(members_by_group[key])
        actual = sorted(a["doc_id"] for a in child["assignments"])
        if actual != expected:
            raise ValueError(
                f"子分析 {child['analysis_id']} 未恰好覆盖父 group {key} 的成员"
            )
        _validate_analysis(child, expected)

    assignments = root["assignments"]
    assigned_ids = [a["doc_id"] for a in assignments]

    chunk_ids = [c["chunk_id"] for c in index["chunks"]]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("chunk_id 重复")
    known_docs = set(assigned_ids)
    for c in index["chunks"]:
        if c["doc_id"] not in known_docs:
            raise ValueError(f"chunk 指向未知文档：{c['doc_id']}")
        if not 0 <= c["start"] < c["end"]:
            raise ValueError(f"chunk 偏移非法：{c}")
        if bodies is not None and c["end"] > len(bodies[c["doc_id"]]):
            raise ValueError(f"chunk 偏移越界：{c}")

    vector_ids = index["vector_doc_ids"]
    if len(set(vector_ids)) != len(vector_ids):
        raise ValueError("vector_doc_ids 重复")
    if not set(vector_ids) <= known_docs:
        raise ValueError("vector_doc_ids 含未出现在 assignments 里的文档")
    # 集合相等而非仅数量相等：数量对得上但装的是另一批 doc_id，行归属会整体错位，
    # 而错位没有任何症状。有块的文档必然有向量，反之亦然。
    if set(vector_ids) != {c["doc_id"] for c in index["chunks"]}:
        raise ValueError("vector_doc_ids 与有块的文档集合不一致")
    if matrix is not None:
        if matrix.ndim != 2:
            raise ValueError(f"向量矩阵必须是二维，得到 {matrix.ndim} 维")
        if matrix.dtype != np.float32:
            raise ValueError(f"向量矩阵必须是 float32，得到 {matrix.dtype}")
        if matrix.shape[0] != len(vector_ids):
            raise ValueError(
                f"向量行数 {matrix.shape[0]} 与 vector_doc_ids {len(vector_ids)} 不符"
            )
        if matrix.shape[0] and matrix.shape[1] == 0:
            raise ValueError("向量维度为零")
        if matrix.size and not np.all(np.isfinite(matrix)):
            raise ValueError("向量矩阵含 NaN 或 Inf")


def write_index(out_dir: Path, index: dict, matrix: np.ndarray) -> None:
    """索引子事务：`index.json` 与向量文件要么都发布，要么都不发布。

    半写入（JSON 在而向量不在，或反过来）会让下游读到一份说谎的索引，
    比完全没有索引更糟。
    """
    out_dir = Path(out_dir)
    try:
        with (out_dir / "index-vectors.npy").open("wb") as fh:
            np.save(fh, matrix.astype(np.float32))
        payload = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=False)
        (out_dir / "index.json").write_text(payload, encoding="utf-8")
    except BaseException:
        # 清理用 BaseException：被 Ctrl-C 打断时同样不能留下半个索引。
        # 但注意本函数**不吞异常**——它照常向上抛，由调用方决定语义。
        cleanup_index_files(out_dir)
        raise


def read_index(out_dir: Path, *, trust_manifest: bool = True) -> tuple[dict, np.ndarray]:
    """下游（2B/2C/2D/2E）读取索引的**唯一**入口。

    文件被截断时 shape 仍可能「看起来合理」，只比对元数据不够——所以这里把
    2A spec §6 要求读取方做的完整性校验一次性做掉，避免三个下游各写一遍、
    各漏一条。

    **默认先问 manifest 这份索引算不算数。** 清理失败时我们选择保住完好的清洗
    产物、让半份索引留在盘上，理由是「manifest 才是权威」——但那句话只有在
    读取入口真的去问 manifest 时才成立，否则它就是一张空头支票：
    一份外观完整的残留文件照样会被下游当真。

    `trust_manifest=False` 只给**管线内部**用：洞察阶段跑在 `write_manifest`
    之前，那时 manifest 还不存在。这是唯一的合法例外，别在别处传。
    """
    out_dir = Path(out_dir)
    if trust_manifest:
        from kb_init.manifest import read_manifest

        try:
            status = read_manifest(out_dir).get("index_status")
        except (OSError, ValueError) as exc:
            # 没有 manifest 就没有权威可问——不猜，直接拒读
            raise ValueError(
                f"读不到 {out_dir}/manifest.json，无法确认这份索引是否算数：{exc}"
            ) from exc
        if status != "complete":
            raise ValueError(
                f"manifest 说这次运行的索引状态是 {status!r}，不是 complete——"
                f"拒绝读取可能是残留或半成品的索引文件。"
            )
    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    matrix = np.load(out_dir / "index-vectors.npy")
    if matrix.ndim != 2:
        raise ValueError(f"向量矩阵必须是二维，得到 {matrix.ndim} 维")
    if matrix.dtype != np.float32:
        raise ValueError(f"向量矩阵必须是 float32，得到 {matrix.dtype}")
    if matrix.size and not np.all(np.isfinite(matrix)):
        raise ValueError("向量矩阵含 NaN 或 Inf")
    expected = len(index["vector_doc_ids"])
    if matrix.shape[0] != expected:
        raise ValueError(f"向量行数 {matrix.shape[0]} 与 vector_doc_ids {expected} 不符")
    return index, matrix


def cleanup_index_files(out_dir: Path) -> None:
    """尽力删掉全部索引文件，**逐个独立尝试**。

    早前写成一个循环里连续 unlink，第一个失败会中断第二个——于是"回滚"只回滚了
    一半，留下的恰恰是最危险的半索引。清理路径本身不能有单点。
    """
    out_dir = Path(out_dir)
    for name in INDEX_FILES:
        try:
            (out_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def index_files_remain(out_dir: Path) -> bool:
    """回滚后的复核：确认没有任何索引文件残留。"""
    return any((Path(out_dir) / name).exists() for name in INDEX_FILES)
