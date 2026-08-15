"""测试用的确定性假 embedder。

向量由 SHA-256 派生而非 Python 内置 hash()——后者带进程级随机盐，
会让测试在不同进程间随机飘。
"""
from __future__ import annotations

import hashlib

import numpy as np


def fake_vector(text: str, dim: int = 8) -> np.ndarray:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = np.frombuffer((digest * ((dim // len(digest)) + 1))[:dim], dtype=np.uint8)
    vec = raw.astype(np.float32) / 255.0
    # 全零向量会在池化处被判非法；给一个稳定的下限保证它永远非零
    vec[0] += 0.5
    return vec


class FakeEmbedder:
    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.model_name = "fake"
        self.revision = "fake-rev"
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        for t in texts:
            yield fake_vector(t, self.dim)


class BrokenEmbedder:
    """按 mode 制造各种非法产出，用于验证 fail closed。"""

    def __init__(self, mode: str, dim: int = 8) -> None:
        self.mode = mode
        self.dim = dim

    def embed(self, texts: list[str]):
        for i, t in enumerate(texts):
            if self.mode == "short" and i == len(texts) - 1:
                return                                  # 少一个向量
            if self.mode == "dim_shift" and i == 1:
                yield np.ones(self.dim + 3, dtype=np.float32)
                continue
            if self.mode == "nan" and i == 0:
                yield np.full(self.dim, np.nan, dtype=np.float32)
                continue
            if self.mode == "inf" and i == 0:
                yield np.full(self.dim, np.inf, dtype=np.float32)
                continue
            if self.mode == "zero" and i == 0:
                yield np.zeros(self.dim, dtype=np.float32)
                continue
            if self.mode == "raise" and i == 1:
                raise RuntimeError("推理中途炸了")
            yield fake_vector(t, self.dim)
