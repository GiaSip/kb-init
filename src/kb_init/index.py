"""组装 index.json 并落盘。本层**唯一**写盘的模块。

`analyses` 从第一天就是数组：将来 residual 二次微聚类需要同时保留「第一轮 residual」
与「第二轮 micro assigned」两套 disposition，单顶层结构表达不了，等到那时再改
就是破坏性迁移。现在多写一层数组是零成本。
"""
from __future__ import annotations

import json
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
    dated_docs: int, total_docs: int, threshold: float = TIME_AXIS_THRESHOLD
) -> dict:
    """只报事实，不做判断：是否变成一条洞察由 2B 决定。

    阈值取在实测的两档语料之间（导出类 5–6%，已维护类 43%），中间是空的，
    0.10–0.40 的任何取值在现有证据下行为相同。
    """
    coverage = (dated_docs / total_docs) if total_docs else 0.0
    return {
        "dated_docs": dated_docs,
        "total_docs": total_docs,
        "coverage": round(coverage, 6),
        "threshold": threshold,
        "available": coverage >= threshold,
        "per_group": None,          # 仅当 available 为真时才由 2B 填充
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
) -> dict:
    dispositions = [a.disposition for a in assignments]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "corpus_hash": corpus_hash,
        "versions": versions,
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


def validate_index(index: dict, kept_doc_ids: Sequence[str]) -> None:
    """合同自检。宁可在写盘前炸，也不要产出一份下游读不懂的索引。"""
    analysis = index["analyses"][0]
    assigned_ids = [a["doc_id"] for a in analysis["assignments"]]
    if len(set(assigned_ids)) != len(assigned_ids):
        raise ValueError("assignment 出现重复 doc_id")
    if sorted(assigned_ids) != sorted(kept_doc_ids):
        raise ValueError("每个 kept 文档必须恰有一条 assignment")

    known_groups = {g["group_id"] for g in analysis["groups"]}
    if len(known_groups) != len(analysis["groups"]):
        raise ValueError("group_id 重复")
    for a in analysis["assignments"]:
        for m in a["memberships"]:
            if m["group_id"] not in known_groups:
                raise ValueError(f"membership 指向不存在的 group：{m['group_id']}")

    counted = {"assigned": 0, "ambiguous": 0, "residual": 0}
    for a in analysis["assignments"]:
        counted[a["disposition"]] += 1
    if counted != analysis["coverage"]:
        raise ValueError("coverage 与 assignments 不自洽")

    for g in analysis["groups"]:
        core = sum(
            1
            for a in analysis["assignments"]
            for m in a["memberships"]
            if m["group_id"] == g["group_id"] and m["role"] == "core"
        )
        if core != g["member_counts"]["core"]:
            raise ValueError(f"{g['group_id']} 的 core 计数与 memberships 不符")


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
        for name in INDEX_FILES:
            (out_dir / name).unlink(missing_ok=True)
        raise
