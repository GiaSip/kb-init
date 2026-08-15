import subprocess
import sys

import pytest

from kb_init.embed import MAX_TOKENS, TokenSafeSplitter, build_splitter


def test_token_safe_splitter_never_exceeds_limit_for_dense_text():
    """每 1 字符算 3 token 的极端计数器——模拟英文/代码把 400 字符撑爆 512 token。"""
    splitter = TokenSafeSplitter(count_tokens=lambda s: len(s) * 3, max_tokens=MAX_TOKENS)
    text = "x" * 2000
    spans = splitter.split(text)
    assert spans, "不该切出空结果"
    for start, end in spans:
        assert (end - start) * 3 <= MAX_TOKENS
    assert "".join(text[s:e] for s, e in spans) == text


def test_token_safe_splitter_keeps_whole_text_when_within_limit():
    splitter = TokenSafeSplitter(count_tokens=lambda s: len(s), max_tokens=MAX_TOKENS)
    text = "短文本"
    assert splitter.split(text) == [(0, len(text))]


def test_token_safe_splitter_on_empty_text():
    splitter = TokenSafeSplitter(count_tokens=len, max_tokens=MAX_TOKENS)
    assert splitter.split("") == []


def test_token_safe_splitter_covers_text_without_gaps_or_overlap():
    splitter = TokenSafeSplitter(count_tokens=lambda s: len(s) * 2, max_tokens=100)
    text = "内容" * 500
    spans = splitter.split(text)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    for (_, prev_end), (next_start, _) in zip(spans, spans[1:]):
        assert prev_end == next_start


def test_build_splitter_falls_back_and_says_so_when_tokenizer_unavailable(monkeypatch):
    """拿不到真 tokenizer 时必须降级并**如实记录**，不能假装是 token-safe。"""
    monkeypatch.setitem(sys.modules, "fastembed", None)
    splitter, meta = build_splitter()
    assert meta["fallback_used"] is True
    assert meta["name"] == "char"
    assert splitter.split("abc") == [(0, 3)]


def test_module_does_not_import_fastembed_at_top_level():
    """--no-index 路径与全部单测都不该因为 import 就拖进 ONNX 运行时。"""
    code = "import kb_init.embed, sys; print('fastembed' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


@pytest.mark.smoke
def test_real_model_smoke():
    """真实模型烟测：不进常规 CI，需已预热模型缓存。

    Run: .venv/bin/python -m pytest -m smoke -q
    """
    from kb_init.embed import DEFAULT_MODEL, FastEmbedEmbedder

    embedder = FastEmbedEmbedder()
    vectors = list(embedder.embed(["测试文本", "second text"]))
    assert len(vectors) == 2
    assert vectors[0].shape == (512,)
    assert all(v.dtype.kind == "f" and bool(v.any()) for v in vectors)

    splitter, meta = build_splitter(DEFAULT_MODEL)
    assert meta["fallback_used"] is False, "真实模型下不该走降级分块"

    # 真正要挡的是「400 字符启发式在英文/代码上失效」——用真 tokenizer 验证
    long_code = "def f():\n    return 1\n" * 200
    from fastembed import TextEmbedding

    tokenizer = TextEmbedding(model_name=DEFAULT_MODEL).model.tokenizer
    for start, end in splitter.split(long_code):
        assert len(tokenizer.encode(long_code[start:end]).ids) <= MAX_TOKENS
