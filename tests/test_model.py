from kb_init.model import Document, compute_content_hash, compute_doc_id


def test_doc_id_is_stable_across_calls():
    assert compute_doc_id("a/b.md") == compute_doc_id("a/b.md")


def test_doc_id_differs_by_path():
    assert compute_doc_id("a/b.md") != compute_doc_id("a/c.md")


def test_doc_id_is_16_hex_chars():
    value = compute_doc_id("a/b.md")
    assert len(value) == 16
    assert all(c in "0123456789abcdef" for c in value)


def test_content_hash_ignores_path():
    assert compute_content_hash(b"same") == compute_content_hash(b"same")
    assert compute_content_hash(b"a") != compute_content_hash(b"b")


def test_document_defaults_to_kept():
    doc = Document(
        doc_id="0" * 16,
        source_relpath="a.md",
        content_hash="1" * 16,
        title="A",
        body="body",
        frontmatter={},
        created=None,
        date_source="unknown",
    )
    assert doc.status == "kept"
    assert doc.drop_reason is None
    assert doc.out_relpath is None
