from kb_init.keywords import DEFAULT_PARAMS, extract_keywords, strip_markdown, tokenize
from kb_init.stopwords import CJK_GLUE, FUNCTION_WORDS, STOPLIST_VERSION


# ---------------- 功能词表 ----------------

def test_covers_the_function_words_seen_in_real_corpora():
    """实测中真的把这些词选成过簇名——它们必须在表里。"""
    for w in ("che", "non", "una", "per", "essere",
              "the", "that", "which", "there", "more", "they",
              "can", "like", "about", "world"):
        assert w in FUNCTION_WORDS, w


def test_does_not_swallow_real_topic_words():
    """表不能宽到把真主题词吃掉——否则名字会全空。"""
    for w in ("grammatica", "design", "backend", "notification", "feedback"):
        assert w not in FUNCTION_WORDS, w


def test_cjk_glue_is_single_characters_only():
    assert CJK_GLUE
    assert all(len(c) == 1 for c in CJK_GLUE)
    for c in ("的", "了", "是", "在", "我", "们", "这", "和", "就", "有"):
        assert c in CJK_GLUE, c


def test_stoplist_version_is_recorded():
    assert STOPLIST_VERSION == "bundled-v1"


# ---------------- 抽取管线 ----------------

def test_strip_markdown_removes_link_targets_images_urls_and_code():
    text = ("![图](assets/a.png) 见 [文档](https://example.com/doc) 与 "
            "`code_token` 还有 https://example.com/bare")
    out = strip_markdown(text)
    assert "assets" not in out and "example.com" not in out
    assert "code_token" not in out
    assert "文档" in out                     # 链接文字要保留，只去目标


def test_tokenize_splits_latin_words_and_cjk_ngrams():
    toks = tokenize("hello 设计方法 world")
    assert "hello" in toks and "world" in toks
    assert "设计" in toks and "设计方" in toks
    assert "h" not in toks                    # 单字符拉丁不成词


def test_function_words_never_become_keywords():
    bodies = {f"d{i}": f"che non una per essere grammatica preposizione verbo{i} " * 5
              for i in range(6)}
    bodies.update({f"o{i}": f"backend api database server{i} " * 5 for i in range(6)})
    got = extract_keywords(bodies, {"g01": [f"d{i}" for i in range(6)]})
    assert got["g01"], "关键词为空会让下面的断言恒真"
    assert not ({"che", "non", "una", "per", "essere"} & set(got["g01"]))
    assert {"grammatica", "preposizione"} & set(got["g01"])


def _varied(sentences, n):
    """语境必须多样。同一句重复 N 遍是**退化文本**：每个 n-gram 只有一个固定
    邻居，邻接熵恒为 0，会把工作正常的边界过滤器判成坏的。真实文本不长这样。"""
    return {f"d{i}": "。".join(s.format(i=i, j=j) for j, s in enumerate(sentences))
            for i in range(n)}


def test_cjk_shift_fragments_are_filtered():
    bodies = _varied([
        "我们这周的推敲重点是造型{i}",
        "上次推敲之后造型改了{i}版",
        "这周把推敲结论整理成造型说明{i}",
        "造型推敲需要更多参考{i}",
        "关于造型的推敲我下周再看{i}",
    ], 6)
    bodies.update({f"o{i}": f"backend api server{i} deploy pipeline" for i in range(6)})
    got = extract_keywords(bodies, {"g01": [f"d{i}" for i in range(6)]})
    assert got["g01"], "关键词为空时下面的断言恒真"
    for junk in ("们这", "是周", "间的", "我们这"):
        assert junk not in got["g01"], junk


def test_overlapping_ngrams_are_deduped():
    bodies = _varied([
        "机器学习的模型训练很慢{i}",
        "这次模型训练用了新数据{i}",
        "训练模型之前先看机器学习基础{i}",
        "模型的训练结果比机器学习课上讲的好{i}",
        "关于训练一个模型的机器学习笔记{i}",
    ], 6)
    bodies.update({f"o{i}": f"unrelated english text{i} about cooking" for i in range(6)})
    got = extract_keywords(bodies, {"g01": [f"d{i}" for i in range(6)]})
    assert got["g01"]
    for a in got["g01"]:
        for b in got["g01"]:
            if a != b:
                assert a not in b and b not in a


def test_is_deterministic():
    bodies = {f"d{i}": f"design pioneers modern architecture {i} " * 6
              for i in range(6)}
    bodies.update({f"o{i}": f"backend api server{i} " * 6 for i in range(6)})
    groups = {"g01": [f"d{i}" for i in range(6)]}
    assert extract_keywords(bodies, groups) == extract_keywords(bodies, groups)


def test_empty_and_tiny_groups_do_not_raise():
    bodies = {"d0": "design", "d1": ""}
    got = extract_keywords(bodies, {"g01": ["d1"], "g02": []})
    assert got == {"g01": [], "g02": []}


def test_top_k_is_respected_when_the_group_is_rich_enough():
    bodies = {f"d{i}": ("alpha bravo charlie delta echo foxtrot golf hotel "
                        f"india juliet kilo{i} ") * 6 for i in range(8)}
    bodies.update({f"o{i}": f"zulu yankee xray{i} " * 6 for i in range(8)})
    got = extract_keywords(bodies, {"g01": [f"d{i}" for i in range(8)]}, top_k=4)
    assert len(got["g01"]) == 4


def test_params_are_exposed_for_recording():
    for key in ("min_lift", "min_cluster_df",
                "cjk_pmi_min_bigram", "cjk_pmi_min_trigram", "stoplist"):
        assert key in DEFAULT_PARAMS
