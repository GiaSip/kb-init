"""簇的无监督命名：混合脚本 c-TF-IDF。

**IDF 必须在真实文档层面算，不能在「每簇拼成一篇」的类文档之间算。** 早期原型
犯过这个错：整簇的停用词因为「只有这一簇是意大利语」而显得极其独特，直接成了簇名。

产出的是**关键词**，不是主题名。渲染层的措辞必须是「这些篇里最具区分度的词是…」，
不能写成「你的主题是…」——那是产物在撒谎。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Mapping, Sequence

from kb_init.stopwords import CJK_GLUE, FUNCTION_WORDS, STOPLIST_VERSION

DEFAULT_PARAMS = {
    "method": "ctfidf_multiscript",
    # 判据是**尺度无关的 lift**（簇内文档占比 ÷ 簇外文档占比），不是全局 df 的
    # 绝对上限。绝对上限看着能用，其实是在拟合「簇占语料多大比例」：29 篇的簇在
    # 757 篇语料里恰好压在 5% 线下，换一份语料或换个簇大小就整批失效。
    "min_lift": 2.0,
    "min_cluster_df": 2,
    "cjk_pmi_min_bigram": 2.0,
    "cjk_pmi_min_trigram": 3.0,
    "cjk_min_boundary_entropy": 0.4,
    "stoplist": STOPLIST_VERSION,
}

_CJK = r"一-鿿㐀-䶿"
_LATIN = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]{2,}")
_CJK_RUN = re.compile(f"[{_CJK}]+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CODE = re.compile(r"```.*?```|`[^`]*`", re.S)


def strip_markdown(text: str) -> str:
    text = _CODE.sub(" ", text)
    text = _IMG.sub(" ", text)
    text = _LINK.sub(r"\1", text)        # 保留链接文字，去掉目标
    return _URL.sub(" ", text)


def tokenize(text: str) -> list[str]:
    text = strip_markdown(text)
    out = [w.lower() for w in _LATIN.findall(text)]
    for run in _CJK_RUN.findall(text):
        out += [run[i:i + 2] for i in range(len(run) - 1)]
        out += [run[i:i + 3] for i in range(len(run) - 2)]
    return out


def _is_cjk(term: str) -> bool:
    return bool(_CJK_RUN.fullmatch(term))


def _cohesive(term: str, stats: "_CjkStats", params: Mapping) -> bool:
    """CJK n-gram 的内聚度（PMI）。滑窗会切出「是周」这类非词，它们的出现频率
    可以完全由各字符独立出现解释——PMI 因此接近零。

    **分母必须同源。** 早期实现拿「全部 token 数」（含 2-gram + 3-gram + 拉丁词）
    当 p_term 的分母，却拿 CJK 字符数当 p_char 的分母——两个概率空间不可比，
    PMI 被系统性压低约 log(2) 以上，把「推敲」「造型」这种真词也一起滤掉了。
    n-gram 的概率只能在**同长度 n-gram 的总数**里算。
    """
    if not _is_cjk(term):
        return True
    if any(c in CJK_GLUE for c in term):
        return False
    n = len(term)
    total = stats.ngram_total.get(n, 0)
    freq = stats.ngram_freq.get(n, {}).get(term, 0)
    if not total or not freq:
        return False
    p_term = freq / total
    p_parts = 1.0
    for c in term:
        p_parts *= stats.char_freq[c] / max(stats.char_total, 1)
    if p_parts <= 0:
        return False
    threshold = (params["cjk_pmi_min_bigram"] if n == 2
                 else params["cjk_pmi_min_trigram"])
    return math.log(p_term / p_parts) > threshold


class _CjkStats:
    """语料级 CJK 统计。字符与各长度 n-gram 的计数分开存，PMI 才有同源分母。"""

    __slots__ = ("char_freq", "char_total", "ngram_freq", "ngram_total")

    def __init__(self, texts: Sequence[str]) -> None:
        self.char_freq: Counter = Counter()
        self.ngram_freq: dict[int, Counter] = {2: Counter(), 3: Counter()}
        self.ngram_total: dict[int, int] = {2: 0, 3: 0}
        for text in texts:
            for run in _CJK_RUN.findall(strip_markdown(text)):
                self.char_freq.update(run)
                for n in (2, 3):
                    for i in range(len(run) - n + 1):
                        self.ngram_freq[n][run[i:i + n]] += 1
                        self.ngram_total[n] += 1
        self.char_total = sum(self.char_freq.values())


def _cjk_neighbors(texts: Sequence[str]) -> tuple[dict, dict]:
    """统计簇内每个 CJK n-gram 的左右邻接字符分布。

    只扫本簇的文档：邻接统计要的就是「在这个语境里它的边界稳不稳」，
    而且簇比整份语料小得多，一趟扫完不值一提。
    """
    left: dict[str, Counter] = {}
    right: dict[str, Counter] = {}
    for text in texts:
        for run in _CJK_RUN.findall(strip_markdown(text)):
            for n in (2, 3):
                for i in range(len(run) - n + 1):
                    term = run[i:i + n]
                    # 词处在 run 的边界上，本身就是最强的边界证据，
                    # 用一个不可能与真实字符碰撞的哨兵表示
                    left.setdefault(term, Counter())[run[i - 1] if i else "\x00"] += 1
                    right.setdefault(term, Counter())[
                        run[i + n] if i + n < len(run) else "\x00"
                    ] += 1
    return left, right


def _entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return -sum(
        (c / total) * math.log(c / total) for c in counter.values() if c
    )


def _boundary_ok(term: str, left: dict, right: dict, min_entropy: float) -> bool:
    """左右邻接熵判据：真词的邻居多样，碎片的邻居近乎固定。

    「励模型」的左边几乎永远是「奖」，「合人类」的左边几乎永远是「符」——
    停用词表治不了这一类，因为它们的字本身都不是功能词。
    """
    if not _is_cjk(term):
        return True
    return (min(_entropy(left.get(term, Counter())),
                _entropy(right.get(term, Counter()))) >= min_entropy)


def _dedupe_overlaps(candidates: Sequence[str], top_k: int) -> list[str]:
    """去掉子串与首尾位移重叠的候选——「我们这」与「们这周」同时出现在名字里，
    读起来像坏掉的分词器，而它确实就是。"""
    picked: list[str] = []
    for term in candidates:
        if any(term in kept or kept in term for kept in picked):
            continue
        if any(len(term) > 1 and len(kept) > 1
               and (term[:-1] == kept[1:] or term[1:] == kept[:-1])
               for kept in picked):
            continue
        picked.append(term)
        if len(picked) == top_k:
            break
    return picked


def extract_keywords(
    bodies: Mapping[str, str],
    groups: Mapping[str, Sequence[str]],
    *,
    top_k: int = 4,
    params: Mapping | None = None,
) -> dict[str, list[str]]:
    params = {**DEFAULT_PARAMS, **(params or {})}
    tokens = {doc_id: tokenize(text) for doc_id, text in bodies.items()}
    total_docs = len(tokens) or 1

    doc_freq: Counter = Counter()
    for toks in tokens.values():
        doc_freq.update(set(toks))

    cjk_stats = _CjkStats(list(bodies.values()))

    result: dict[str, list[str]] = {}
    for group_id, member_ids in groups.items():
        members = [d for d in member_ids if d in tokens]
        term_freq: Counter = Counter()
        cluster_df: Counter = Counter()
        for d in members:
            term_freq.update(tokens[d])
            cluster_df.update(set(tokens[d]))
        term_total = sum(term_freq.values())
        if not term_total:
            result[group_id] = []
            continue

        left_nb, right_nb = _cjk_neighbors([bodies[d] for d in members])

        outside_docs = max(total_docs - len(members), 1)
        # 簇外一次都没出现的词不该拿到无穷大的 lift，否则只出现两次的偶然词
        # 会压过真正的主题词。给簇外占比一个下限，相当于「半篇」的先验。
        outside_floor = 0.5 / outside_docs

        scored: dict[str, float] = {}
        for term, freq in term_freq.items():
            if len(term) < 2 or term in FUNCTION_WORDS:
                continue
            if cluster_df[term] < params["min_cluster_df"]:
                continue
            if not _cohesive(term, cjk_stats, params):
                continue
            if not _boundary_ok(term, left_nb, right_nb,
                                params["cjk_min_boundary_entropy"]):
                continue
            inside_ratio = cluster_df[term] / len(members)
            outside_ratio = max(
                (doc_freq[term] - cluster_df[term]) / outside_docs, outside_floor
            )
            lift = inside_ratio / outside_ratio
            if lift < params["min_lift"]:
                continue
            scored[term] = inside_ratio * math.log(lift)

        # 分数相等时按词本身排序破平——否则同输入两次跑可能给出不同的名字
        ordered = [t for t, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))]
        result[group_id] = _dedupe_overlaps(ordered, top_k)
    return result
