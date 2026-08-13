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
