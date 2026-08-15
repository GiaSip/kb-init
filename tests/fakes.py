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


class BlobEmbedder:
    """几何可控的假 embedder：按文本里的标记把向量放到指定方向上。

    FakeEmbedder 的向量由 SHA-256 派生，几何形状不可控——想在管线级测试里
    稳定造出「有簇 + 有 residual」的局面就只能碰运气。这个实现让测试自己
    决定形状，同时仍然完全确定（jitter 也来自 hash，不用随机数）。

    约定：正文里出现 `blob:<name>` 就归到 <name> 这个方向；出现 `blob:noise`
    则每篇各自一个方向（用于制造 residual）。
    """

    def __init__(self, dim: int = 8, jitter: float = 0.01) -> None:
        self.dim = dim
        self.jitter = jitter
        self.model_name = "blob"
        self.revision = "blob-rev"
        self._axes: dict[str, int] = {}

    def _axis(self, name: str) -> int:
        if name not in self._axes:
            self._axes[name] = len(self._axes) % self.dim
        return self._axes[name]

    def embed(self, texts: list[str]):
        for text in texts:
            marker = "noise"
            for token in text.split():
                if token.startswith("blob:"):
                    marker = token[len("blob:"):]
                    break
            vec = np.zeros(self.dim, dtype=np.float32)
            if marker == "noise":
                # 每篇一个自己的方向：彼此不成簇，落进 residual。
                # **必须中心化**：uint8 全是非负数，不减 127.5 的话所有噪声向量
                # 都挤在同一个象限里，反而会自己聚成一簇——第一版就踩了这个坑。
                digest = hashlib.sha256(text.encode("utf-8")).digest()
                raw = np.frombuffer(digest[: self.dim], dtype=np.uint8)
                vec += raw.astype(np.float32) - 127.5
            else:
                vec[self._axis(marker)] = 1.0
                digest = hashlib.sha256(text.encode("utf-8")).digest()
                vec += self.jitter * (
                    np.frombuffer(digest[: self.dim], dtype=np.uint8).astype(np.float32)
                    / 255.0
                )
            yield vec / np.linalg.norm(vec)
