# tests/test_manifest.py
from kb_init.manifest import (
    SCHEMA_VERSION, compute_corpus_hash, read_manifest, write_manifest,
)
from kb_init.model import Document


def _doc(doc_id: str, status: str = "kept") -> Document:
    return Document(
        doc_id=doc_id.ljust(16, "0"),
        source_relpath=f"{doc_id}.md",
        content_hash=doc_id.ljust(16, "f"),
        title="t",
        body="x" * 300,
        frontmatter={},
        status=status,
        out_relpath=f"knowledge/{doc_id}.md" if status == "kept" else None,
    )


def test_corpus_hash_is_order_independent():
    a, b = _doc("a"), _doc("b")
    assert compute_corpus_hash([a, b]) == compute_corpus_hash([b, a])


def test_corpus_hash_changes_with_content():
    a = _doc("a")
    modified = _doc("a")
    modified.content_hash = "9" * 16
    assert compute_corpus_hash([a]) != compute_corpus_hash([modified])


def test_manifest_roundtrip(tmp_path):
    docs = [_doc("a"), _doc("b", status="dropped")]
    docs[1].drop_reason = "stub"
    write_manifest(docs, tmp_path, run_id="run-1", source="/x/export")
    data = read_manifest(tmp_path)
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["run_id"] == "run-1"
    assert data["source"] == "/x/export"
    assert data["counts"]["total"] == 2
    assert data["counts"]["kept"] == 1
    assert len(data["documents"]) == 2


def test_dropped_documents_are_recorded_with_reason(tmp_path):
    dropped = _doc("b", status="dropped")
    dropped.drop_reason = "stub"
    write_manifest([dropped], tmp_path, run_id="r", source="s")
    entry = read_manifest(tmp_path)["documents"][0]
    assert entry["status"] == "dropped"
    assert entry["drop_reason"] == "stub"
    assert entry["out_relpath"] is None
