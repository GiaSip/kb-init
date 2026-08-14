from kb_init.clean import CleanConfig, mark, summarize
from kb_init.model import Document


def _doc(doc_id: str, body: str, content_hash: str = None) -> Document:
    return Document(
        doc_id=doc_id,
        source_relpath=f"{doc_id}.md",
        content_hash=content_hash or doc_id.ljust(16, "0"),
        title="t",
        body=body,
        frontmatter={},
    )


def test_short_body_marked_as_stub():
    docs = mark([_doc("a", "太短")])
    assert docs[0].status == "dropped"
    assert docs[0].drop_reason == "stub"


def test_long_body_is_kept():
    docs = mark([_doc("a", "x" * 500)])
    assert docs[0].status == "kept"
    assert docs[0].drop_reason is None


def test_duplicate_marked_with_first_doc_id():
    docs = mark([
        _doc("aaa", "x" * 500, content_hash="H" * 16),
        _doc("bbb", "x" * 500, content_hash="H" * 16),
    ])
    assert docs[0].status == "kept"
    assert docs[1].status == "dropped"
    assert docs[1].drop_reason == "duplicate:aaa"


def test_list_length_never_shrinks():
    """核心不变量：清洗是标记不是删除。"""
    inputs = [_doc(str(i), "短") for i in range(10)]
    assert len(mark(inputs)) == 10


def test_summarize_counts_by_reason():
    docs = mark([
        _doc("a", "x" * 500, content_hash="H" * 16),
        _doc("b", "x" * 500, content_hash="H" * 16),
        _doc("c", "短"),
    ])
    assert summarize(docs) == {
        "total": 3, "kept": 1, "dropped_stub": 1, "dropped_duplicate": 1,
    }


def test_threshold_is_configurable():
    docs = mark([_doc("a", "x" * 100)], CleanConfig(min_body_chars=50))
    assert docs[0].status == "kept"
