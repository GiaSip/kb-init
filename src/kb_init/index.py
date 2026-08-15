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
) -> dict:
    dispositions = [a.disposition for a in assignments]
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
            {
                "analysis_id": ANALYSIS_ID,
                "parent_analysis_id": None,
                "input_scope": {"kind": "all_kept_docs"},
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
        ],
    }


_DISPOSITIONS = {"assigned", "ambiguous", "residual"}
_ROLES = {"hard", "core", "halo", "micro", "member"}


def validate_index(
    index: dict,
    kept_doc_ids: Sequence[str],
    matrix: "np.ndarray | None" = None,
    bodies: dict[str, str] | None = None,
) -> None:
    """合同自检。宁可在写盘前炸，也不要产出一份下游读不懂、或会说谎的索引。

    校验范围刻意覆盖到「结构合法但语义在撒谎」的形态——例如 residual 却带着
    membership、representative 不属于本簇、向量行数对不上——这类问题不会让
    任何东西崩溃，只会让 2B 悄悄算错。
    """
    analysis = index["analyses"][0]
    assignments = analysis["assignments"]

    assigned_ids = [a["doc_id"] for a in assignments]
    if len(set(assigned_ids)) != len(assigned_ids):
        raise ValueError("assignment 出现重复 doc_id")
    if sorted(assigned_ids) != sorted(kept_doc_ids):
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
