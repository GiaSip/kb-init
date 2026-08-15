from kb_init.chunk import CharSplitter, chunk_documents


def test_chunks_can_reconstruct_original_text():
    """偏移必须能逐字重建原块——这是 chunks 只存偏移不存正文的前提。"""
    text = "中文内容" * 300           # 1200 字符，跨多块
    chunks = chunk_documents([("d1", text)], CharSplitter(max_chars=400))
    assert len(chunks) == 3
    rebuilt = "".join(text[c.start:c.end] for c in chunks)
    assert rebuilt == text


def test_chunk_ids_are_unique_and_map_back_to_doc():
    docs = [("d1", "a" * 500), ("d2", "b" * 100)]
    chunks = chunk_documents(docs, CharSplitter(max_chars=400))
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert [c.doc_id for c in chunks] == ["d1", "d1", "d2"]


def test_empty_document_produces_no_chunks():
    """空文档不产块。调用方据此给它 residual，而不是让它变成零向量。"""
    assert chunk_documents([("d1", "")], CharSplitter()) == []


def test_exact_multiple_does_not_produce_trailing_empty_chunk():
    chunks = chunk_documents([("d1", "x" * 800)], CharSplitter(max_chars=400))
    assert len(chunks) == 2
    assert chunks[-1].end == 800
