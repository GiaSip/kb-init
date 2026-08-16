"""Wrapped 报告：呈现层。

这一层的两条硬约束都在这里落地：语料内容进 HTML 是真实攻击面（DESIGN R13），
以及「产物不许撒谎」——一条被截断坐标轴的柱子就是在撒谎。
"""
import pytest

from kb_init.report import (
    ReportContractError,
    bar_width,
    esc,
    render_private,
)


# ---------------- 转义 ----------------

@pytest.mark.parametrize("raw,must_not_contain", [
    ("<script>alert(1)</script>", "<script"),
    ('" onload="alert(1)', 'onload="'),
    ("'><img src=x onerror=alert(1)>", "<img"),
    ("a & b", "a & b"),
])
def test_esc_neutralizes_breakouts(raw, must_not_contain):
    assert must_not_contain not in esc(raw)


def test_esc_covers_all_five_characters():
    """逐字对照期望实体。

    ⚠️ 不能写成「转义后不含 `&`」——实体本身就以 `&` 开头，那条断言恒假；
    反过来「转义后不含 `<`」倒是恒真的候选，所以这里直接比对完整输出。
    """
    assert esc("""<>&"\'""") == "&lt;&gt;&amp;&quot;&#x27;"


def test_esc_leaves_normal_text_alone():
    """配对正例：只测「坏的被挡住」的话，一个把全部输入转成空串的实现也全绿。"""
    for text in ["这 29 篇里最具区分度的词是 排版", "InDesign typography", "présente"]:
        assert esc(text) == text


# ---------------- 条形宽度（唯一进 CSS 的值） ----------------

def test_bar_width_is_proportional_from_zero():
    """两个宽度之比必须等于两个篇数之比。截断坐标轴即红。"""
    wide = float(bar_width(32, 32))
    narrow = float(bar_width(8, 32))
    assert wide == pytest.approx(100.0)
    assert narrow / wide == pytest.approx(8 / 32)


def test_bar_width_has_fixed_format():
    """固定一位小数：进 CSS 的值不许出现科学计数法或超长小数。"""
    assert bar_width(1, 3) == "33.3"
    assert bar_width(1, 10**9) == "0.0"


@pytest.mark.parametrize("part,expected", [(-5, "0.0"), (40, "100.0")])
def test_bar_width_clamps(part, expected):
    assert bar_width(part, 32) == expected


@pytest.mark.parametrize("part", [float("nan"), float("inf"), "29", None, [1]])
def test_bar_width_rejects_non_numeric_and_non_finite(part):
    """不静默取 0——取 0 是猜。而且字符串一旦流进 style 属性就是 CSS 注入面。"""
    with pytest.raises(ReportContractError):
        bar_width(part, 32)


def test_bar_width_zero_whole_is_not_a_crash():
    assert bar_width(0, 0) == "0.0"


def test_bar_width_accepts_plain_numbers():
    """配对正例：一个恒抛错的实现也能让上面那组负例全绿。"""
    assert bar_width(1, 2) == "50.0"
    assert bar_width(1.5, 3) == "50.0"


# ---------------- 私有版渲染 ----------------

def _insight(iid, family="topic", kind="topic_cluster", **over):
    item = {
        "insight_id": iid, "family": family, "kind": kind,
        "payload": {"keywords": ["排版", "typography"], "doc_count": 9,
                    "share_of_kept": 0.031,
                    "evidence_titles": ["标题一", "带  多余  空格"]},
        "canonical_text": f"{iid} 的断言句",
        "evidence": {"doc_ids": [], "stat": None},
        "claude_md": {"section": "focus_areas"},
    }
    item.update(over)
    return item


def _payload(*insights, **top):
    out = {"schema_version": "0.1", "run_id": "r1", "corpus_hash": "c1",
           "counts": {"topic": 1, "residual": 0, "corpus": 0, "total": 1},
           "insights": list(insights) or [_insight("T1")]}
    out.update(top)
    return out


def _corpus(iid="C1"):
    return _insight(iid, family="corpus", kind="retention",
                    payload={"total": 620, "kept": 287, "dropped_stub": 333,
                             "dropped_duplicate": 0},
                    canonical_text=f"{iid} 读入 620 篇，留下 287 篇",
                    claude_md=None)


def test_every_insight_appears_with_its_id():
    """呈现层与操作层唯一的接缝：报告不印短 ID，用户看完回到清单找不到对应哪条。"""
    payload = _payload(_insight("T1"), _insight("T2"), _corpus("C1"))
    out = render_private(payload)
    for iid in ("T1", "T2", "C1"):
        assert iid in out


def test_assertive_text_is_canonical_verbatim():
    payload = _payload(_insight("T1", canonical_text="这 29 篇里最具区分度的词是 甲 · 乙"))
    assert "这 29 篇里最具区分度的词是 甲 · 乙" in render_private(payload)


def test_script_tag_in_title_is_escaped():
    item = _insight("T1")
    item["payload"]["evidence_titles"] = ["<script>alert(1)</script>"]
    out = render_private(_payload(item))
    assert "<script>alert(1)" not in out
    assert "&lt;script&gt;" in out


def test_script_tag_in_keyword_is_escaped():
    """关键词同样来自语料，同样是攻击面——只测标题会漏掉半边。"""
    item = _insight("T1")
    item["payload"]["keywords"] = ["<img src=x onerror=alert(1)>"]
    out = render_private(_payload(item))
    assert "<img" not in out


def test_canonical_text_is_escaped_too():
    item = _insight("T1", canonical_text="<b>加粗</b>的断言")
    out = render_private(_payload(item))
    assert "<b>加粗</b>" not in out and "&lt;b&gt;" in out


def test_bare_url_in_title_is_not_linkified():
    """真实语料的证据标题里就含裸 URL。它必须是纯文本，不能被自动变成链接。"""
    item = _insight("T1")
    item["payload"]["evidence_titles"] = ["https://example.com/p/abc123"]
    out = render_private(_payload(item))
    assert "example.com" in out
    assert "href=" not in out


def test_no_reference_constructs():
    """判据是「制造引用的构造」而不是子串 http——真实标题里就含裸 URL，
    扫 http 会与「canonical_text 逐字显示」直接冲突，而被转义的 URL 点不开。"""
    out = render_private(_payload(_insight("T1"), _corpus()))
    for construct in ("src=", "href=", "<script", "@import", "url(", "<iframe", "<form"):
        assert construct not in out, construct


def test_csp_meta_present():
    out = render_private(_payload(_insight("T1")))
    for directive in ("default-src 'none'", "style-src 'unsafe-inline'",
                      "form-action 'none'", "base-uri 'none'"):
        assert directive in out, directive


def test_next_step_block_present():
    """报告是验收界面。看完不知道该干什么，闭环照样在人那一步断掉。"""
    out = render_private(_payload(_insight("T1")))
    assert "insights.md" in out and "compile" in out


def test_sections_follow_family_order():
    payload = _payload(_corpus("C1"),
                       _insight("R1", family="residual", kind="fragment_zone"),
                       _insight("T1"))
    out = render_private(payload)
    assert out.index("主题") < out.index("碎片区") < out.index("语料")


def test_bar_width_appears_only_in_style_attribute():
    """条形宽度是唯一进 CSS 的值——如果它出现在别处，说明模板漏了转义边界。"""
    out = render_private(_payload(_insight("T1")))
    import re
    for value in re.findall(r'style="([^"]*)"', out):
        assert re.fullmatch(r"width:\s*\d+\.\d%", value), value


def test_bars_are_drawn_only_for_topics():
    """碎片区与语料不画条形。

    这条是把报告真渲染出来才发现的：按全局最大值缩放时，碎片区（637 篇）与
    语料（757 篇）会把尺度吃光，主题（5–29 篇）全挤成看不见的红点。
    而且跨节比较条形长度本身就是误导——两节的「篇数」不是同一把尺子。
    """
    import re

    payload = _payload(_insight("T1"),
                       _insight("R1", family="residual", kind="fragment_zone",
                                payload={"count": 637, "share_of_kept": 0.84}),
                       _corpus("C1"))
    out = render_private(payload)
    bars = re.findall(r'style="width: ([\d.]+)%"', out)
    assert len(bars) == 1, f"只有主题该有条形，实际 {len(bars)} 条"


def test_topic_bars_scale_to_the_largest_topic():
    """尺度是主题里最大的那个：最大的主题必须满格，否则一节里没有任何区分度。"""
    import re

    payload = _payload(_insight("T1", payload={"doc_count": 29, "keywords": ["a"]}),
                       _insight("T2", payload={"doc_count": 5, "keywords": ["b"]}),
                       _insight("R1", family="residual", kind="fragment_zone",
                                payload={"count": 637}))
    bars = [float(w) for w in
            re.findall(r'style="width: ([\d.]+)%"', render_private(payload))]
    assert bars[0] == 100.0, "最大的主题应当满格"
    assert bars[1] == pytest.approx(100.0 * 5 / 29, abs=0.05)
