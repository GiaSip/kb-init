#!/usr/bin/env python3
"""R2 验收探针 — 在真实笔记语料上验本地 embedding 的聚类质量。

DESIGN §7 把本地 embedding 裁给了 `BAAI/bge-small-zh-v1.5`，但同一行标了
「C-MTEB 的聚类单项并未压倒 E5，真实笔记聚类仍需验证——不拿排行榜代替验收」。
这个探针就是那次验收：把 kb-init 的产物喂进模型，把簇连同成员标题打印出来，
由人判断「这些簇认不认得出来」。**没有自动通过标准**——聚类质量的验收对象是
"人能不能一眼说出这簇是什么"，任何 silhouette 分数都替代不了这一句。

分块是强制的（DESIGN §7）：bge 上限 512 token，不分块则长笔记被静默截断，
benchmark 再好也没意义。中文近似 1 字 1 token，故按字符切到 400 以内。

用法：
    uv run --with fastembed --with scikit-learn --with numpy \
        probes/cluster_quality_probe.py <kb输出目录> [--model NAME] [-k 12]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.metrics import silhouette_score

_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.S)
_CHUNK_CHARS = 400          # < 512 token，中文近似 1 字 1 token，留足余量


def load_docs(knowledge: Path) -> list[tuple[str, str]]:
    """返回 [(标题, 正文)]。标题取输出文件名 stem——那正是 slug 化后的标题。"""
    docs = []
    for path in sorted(knowledge.glob("*.md")):
        text = _FRONTMATTER.sub("", path.read_text(encoding="utf-8"))
        body = text.strip()
        if body:
            docs.append((path.stem, body))
    return docs


def chunk(text: str) -> list[str]:
    return [text[i:i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)] or [text]


def doc_vectors(model: TextEmbedding, docs: list[tuple[str, str]]) -> np.ndarray:
    """先分块 embedding，再平均池化成文档向量，最后 L2 归一化。"""
    chunks: list[str] = []
    owners: list[int] = []
    for i, (_, body) in enumerate(docs):
        for piece in chunk(body):
            chunks.append(piece)
            owners.append(i)

    print(f"  {len(docs)} 篇 → {len(chunks)} 块，开始 embedding…", file=sys.stderr)
    vecs = np.array(list(model.embed(chunks)))

    dim = vecs.shape[1]
    pooled = np.zeros((len(docs), dim), dtype=np.float32)
    counts = np.zeros(len(docs), dtype=np.float32)
    for vec, owner in zip(vecs, owners):
        pooled[owner] += vec
        counts[owner] += 1
    pooled /= counts[:, None]
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return pooled / np.clip(norms, 1e-9, None)


def report(docs, labels, tag: str, vectors) -> None:
    """标签 -1 表示噪声（HDBSCAN 才会产生）——**不入簇是允许的**。

    KMeans 强制每篇都归到某个簇，语料里本来就零散的那部分会被摊进最近的簇，
    把它稀释成"大杂烩"。L2 洞察不需要每篇都有归属：宁可说"这 40 篇没有主题"，
    也不要造一个看不出是什么的簇。
    """
    ids = sorted(set(labels))
    clustered = [i for i in range(len(docs)) if labels[i] != -1]
    sil = (
        silhouette_score(vectors[clustered], [labels[i] for i in clustered])
        if len(set(labels[i] for i in clustered)) > 1 else float("nan")
    )
    noise = sum(1 for x in labels if x == -1)
    print(f"\n{'=' * 70}\n{tag}  簇数={len([i for i in ids if i != -1])}  "
          f"未归类={noise}/{len(docs)}  silhouette={sil:.3f}"
          f"\n   ← 分数只作参考，验收标准是下面的簇认不认得出来\n{'=' * 70}")
    for cid in ids:
        members = [docs[i][0] for i in range(len(docs)) if labels[i] == cid]
        name = "未归类（噪声）" if cid == -1 else f"簇 {cid}"
        print(f"\n【{name}】{len(members)} 篇")
        for title in members[:12]:
            print(f"    {title}")
        if len(members) > 12:
            print(f"    …… 另 {len(members) - 12} 篇")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kb_dir", type=Path, help="kb-init 的输出目录（含 knowledge/）")
    ap.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    ap.add_argument("-k", "--clusters", type=int, nargs="+", default=[12])
    ap.add_argument("--hdbscan", type=int, nargs="+", default=[],
                    help="按给定的 min_cluster_size 跑 HDBSCAN（允许不归类）")
    ap.add_argument("--cache", type=Path, help="向量缓存 .npy，避免重复 embedding")
    args = ap.parse_args()

    knowledge = args.kb_dir / "knowledge"
    if not knowledge.is_dir():
        sys.exit(f"找不到 {knowledge}")

    docs = load_docs(knowledge)
    if args.cache and args.cache.exists():
        vectors = np.load(args.cache)
        print(f"复用缓存向量 {args.cache}", file=sys.stderr)
    else:
        print(f"模型 {args.model}", file=sys.stderr)
        vectors = doc_vectors(TextEmbedding(model_name=args.model), docs)
        if args.cache:
            args.cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(args.cache, vectors)

    for k in args.clusters:
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(vectors)
        report(docs, labels, f"KMeans k={k}", vectors)

    for mcs in args.hdbscan:
        labels = HDBSCAN(min_cluster_size=mcs, metric="euclidean").fit_predict(vectors)
        report(docs, labels, f"HDBSCAN min_cluster_size={mcs}", vectors)


if __name__ == "__main__":
    main()
