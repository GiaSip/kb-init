"""文档 → 块。只产生映射，不写盘（写盘统一在 index.py）。

偏移单位是 Python `str` 索引（Unicode code point）而非字节：语料是中英意混排，
用字节偏移会在重建时错位。`text[start:end]` 必须逐字等于原块。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    start: int
    end: int


class Splitter(Protocol):
    """把正文切成不超过模型 token 上限的片段，返回 (start, end) 偏移对。"""

    def split(self, text: str) -> list[tuple[int, int]]: ...


@dataclass(frozen=True)
class CharSplitter:
    """按字符数切分。

    这是**降级实现**：中文近似 1 字 1 token，但英文/代码/长符号串可能在 400 字符内
    突破 512 token。真实分块走 embed.py 的 TokenSafeSplitter，此实现用于无 tokenizer
    可用时的兜底与测试。
    """

    max_chars: int = 400

    def split(self, text: str) -> list[tuple[int, int]]:
        if not text:
            return []
        return [
            (i, min(i + self.max_chars, len(text)))
            for i in range(0, len(text), self.max_chars)
        ]


def chunk_documents(
    docs: Sequence[tuple[str, str]], splitter: Splitter
) -> list[Chunk]:
    """`docs` 形如 [(doc_id, 正文)]。空文档产出 0 个块。"""
    chunks: list[Chunk] = []
    seq = 0
    for doc_id, text in docs:
        for start, end in splitter.split(text):
            seq += 1
            chunks.append(Chunk(f"c{seq:05d}", doc_id, start, end))
    return chunks
