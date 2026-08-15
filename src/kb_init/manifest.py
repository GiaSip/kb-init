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
    docs: list[Document],
    out_dir: Path,
    run_id: str,
    source: str,
    unresolved_links: list[dict] | None = None,
    skipped_inputs: list[dict] | None = None,
    index_status: str = "skipped",
    index_reason: str | None = None,
    insights_status: str = "skipped",
    insights_reason: str | None = None,
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
        "unresolved_links": unresolved_links or [],
        "skipped_inputs": skipped_inputs or [],
        # 只看「有没有 index.json」分不清 skipped / failed / 旧版本产物，
        # 事后诊断不能只靠 stderr 和退出码。
        "index_status": index_status,
        "index_reason": index_reason,
        # 洞察层与索引层分开记：只看「有没有 insights.json」分不清
        # skipped（没索引）/ failed（索引在但洞察挂了）/ 旧版本产物。
        "insights_status": insights_status,
        "insights_reason": insights_reason,
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
