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
        [sys.executable, "-c", code], capture_output=True, text=True,
        check=True, encoding="utf-8",
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

    # 真正要挡的是「长文被整篇当成一块」。这里必须先关掉 tokenizer 的 truncation，
    # 否则 len(ids) 恒 ≤512，断言恒真——这条测试曾经就是这么空跑的。
    from fastembed import TextEmbedding

    tokenizer = TextEmbedding(model_name=DEFAULT_MODEL).model.tokenizer
    tokenizer.no_truncation()

    long_code = "def f():\n    return 1\n" * 200
    spans = splitter.split(long_code)
    assert len(spans) > 1, "长文必须被切成多块，否则超出上限的部分会被静默截断"
    for start, end in spans:
        assert len(tokenizer.encode(long_code[start:end]).ids) <= MAX_TOKENS

    long_chinese = "这是一段很长的中文笔记内容。" * 200
    zh_spans = splitter.split(long_chinese)
    assert len(zh_spans) > 1
    for start, end in zh_spans:
        assert len(tokenizer.encode(long_chinese[start:end]).ids) <= MAX_TOKENS
    assert "".join(long_chinese[s:e] for s, e in zh_spans) == long_chinese


def test_splitter_raises_when_a_single_character_exceeds_the_limit():
    """单字符都放不下时必须显式报错——静默放行就是又一次静默截断。"""
    splitter = TokenSafeSplitter(count_tokens=lambda s: len(s) * 1000, max_tokens=10)
    with pytest.raises(ValueError, match="单个字符"):
        splitter.split("abc")


def test_build_splitter_falls_back_when_truncation_cannot_be_disabled(monkeypatch):
    """关不掉 truncation 就不能自称 token-safe——计数会恒 ≤ 上限，等于没在计数。"""
    import types

    class CappedTokenizer:
        """模拟一个关不掉截断的 tokenizer：编码结果永远被截到 8 个 token。"""

        def encode(self, text):
            return types.SimpleNamespace(ids=[0] * min(len(text), 8))

    class FakeModel:
        tokenizer = CappedTokenizer()

    class FakeTextEmbedding:
        def __init__(self, model_name=None):
            self.model = FakeModel()

    fake_module = types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    monkeypatch.setitem(sys.modules, "fastembed", fake_module)

    splitter, meta = build_splitter()
    assert meta["fallback_used"] is True, "关不掉截断时必须如实标记为降级"
