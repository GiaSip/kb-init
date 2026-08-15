import numpy as np
import pytest

from kb_init.chunk import Chunk
from kb_init.embed import EmbeddingError, pool_chunk_vectors
from tests.fakes import BrokenEmbedder, fake_vector


def _chunks():
    return [
        Chunk("c1", "d2", 0, 4),
        Chunk("c2", "d2", 4, 8),
        Chunk("c3", "d1", 0, 4),
    ]


def test_pooling_averages_chunks_then_l2_normalizes():
    chunks = _chunks()
    vectors = [np.array([1.0, 0.0], np.float32),
               np.array([0.0, 1.0], np.float32),
               np.array([3.0, 4.0], np.float32)]
    doc_ids, matrix = pool_chunk_vectors(chunks, vectors)

    # 行序按 doc_id 升序，与块的出现顺序无关
    assert doc_ids == ["d1", "d2"]
    # d1 只有一块 (3,4)，归一化后是 (0.6, 0.8)
    assert np.allclose(matrix[0], [0.6, 0.8])
    # d2 两块均值 (0.5,0.5)，归一化后是 (√2/2, √2/2)
    assert np.allclose(matrix[1], [2 ** -0.5, 2 ** -0.5])
    assert matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)


@pytest.mark.parametrize("mode", ["short", "dim_shift", "nan", "inf", "zero"])
def test_illegal_embedder_output_fails_closed(mode):
    """坏向量绝不能被写进产物——宁可整个索引失败。"""
    chunks = _chunks()
    texts = ["a", "b", "c"]
    broken = BrokenEmbedder(mode=mode, dim=2)
    with pytest.raises(EmbeddingError):
        pool_chunk_vectors(chunks, list(broken.embed(texts)))


def test_embedder_raising_midway_is_not_swallowed():
    with pytest.raises(RuntimeError):
        list(BrokenEmbedder(mode="raise", dim=2).embed(["a", "b", "c"]))


def test_fake_embedder_is_deterministic_across_calls():
    assert np.array_equal(fake_vector("同一段文本"), fake_vector("同一段文本"))


def test_empty_chunk_list_returns_empty_result():
    doc_ids, matrix = pool_chunk_vectors([], [])
    assert doc_ids == []
    assert matrix.shape[0] == 0
