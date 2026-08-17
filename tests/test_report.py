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
    render_share,
    share_keywords,
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
        # ⚠️ 断言句里**不放 ID**：早先写的是 f"{iid} 的断言句"，于是
        # 「每条都印了短 ID」那条测试在 ID 标签被整个删掉之后照样全绿。
        "canonical_text": "这 9 篇里最具区分度的词是 甲 · 乙",
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
                    canonical_text="读入 620 篇，留下 287 篇",
                    claude_md=None)


def test_every_insight_appears_with_its_id():
    """呈现层与操作层唯一的接缝：报告不印短 ID，用户看完回到清单找不到对应哪条。

    断言盯的是**那个 ID 标签**而不是「ID 字符串出现在页面某处」——
    后者会被断言句里碰巧出现的同名字符串喂饱。
    """
    payload = _payload(_insight("T1"), _insight("T2"), _corpus("C1"))
    out = render_private(payload)
    for iid in ("T1", "T2", "C1"):
        assert f'class="id">{iid}<' in out, iid


def test_assertive_text_is_canonical_verbatim():
    payload = _payload(_insight("T1", canonical_text="这 29 篇里最具区分度的词是 丙 · 丁"))
    assert "这 29 篇里最具区分度的词是 丙 · 丁" in render_private(payload)


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
    # ⚠️ 用 example.com，不用真实语料里那条 URL。测试 fixture 也是仓库内容，
    # 而这个仓库要开源——从真实笔记里抄一条 URL 进来，就是把用户的数据发出去了。
    item["payload"]["evidence_titles"] = ["https://example.com/p/abc123"]
    out = render_private(_payload(item))
    assert "example.com/p/abc123" in out
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


# ---------------- 分享版与 allowlist ----------------

def _all_checked(payload):
    return {i["insight_id"]: True for i in payload["insights"]}


def _share(payload, selections=None):
    return render_share(payload, selections or _all_checked(payload))


@pytest.mark.parametrize("needle", [
    "标题一",                 # evidence_titles
    "RUNID-9f3a",             # run_id
    "CORPUSHASH-7b21",        # corpus_hash
    "ctfidf_multiscript",     # naming.params
])
def test_share_omits_every_denied_field(needle):
    """⚠️ 探针值刻意取得可辨识：早先用 run_id="r1" / corpus_hash="c1"，
    而 "c1" 与洞察 ID `C1` 撞了，这条断言于是在测一件与它声称无关的事。"""
    payload = _payload(_insight("T1"), _corpus("C1"),
                       run_id="RUNID-9f3a", corpus_hash="CORPUSHASH-7b21",
                       naming={"method": "ctfidf_multiscript", "params": {}},
                       limits={"topic_insight_cap": 12})
    assert needle not in _share(payload)


def test_share_omits_evidence_doc_ids():
    item = _insight("T1")
    item["payload"]["evidence_doc_ids"] = ["notion-export-私密文件名"]
    assert "私密文件名" not in _share(_payload(item))


def test_share_keeps_allowed_fields():
    """配对正例：把整份内容删光也能让上面那组负例全绿。"""
    out = _share(_payload(_insight("T1"), _corpus("C1")))
    assert "排版" in out and "typography" in out      # keywords
    assert 'class="id">T1<' in out                     # 短 ID
    assert "这 9 篇里最具区分度的词是 甲 · 乙" in out    # canonical_text


def test_share_only_contains_checked_items():
    payload = _payload(_insight("T1"),
                       _insight("T2", payload={"keywords": ["秘密关键词"],
                                               "doc_count": 3},
                                canonical_text="T2 的句子"))
    out = render_share(payload, {"T1": True, "T2": False})
    assert "T2" not in out
    assert "秘密关键词" not in out, "取消勾选的条目，它的关键词也不该出现"


def test_share_disclosure_present():
    out = _share(_payload(_insight("T1")))
    assert "不包含" in out and "标题" in out


def test_share_is_built_from_scratch_not_filtered():
    """守住「从零构造」而不是「拿私有版删几处」。

    payload 里多一个未列入 allowlist 的字段，它绝不能自动出现在分享版里——
    否则上游每加一个字段，分享版就默默多泄露一样东西，而没有任何症状。
    """
    item = _insight("T1")
    item["payload"]["future_field"] = "上游以后新加的东西"
    item["source_path"] = "/somewhere/私密路径.md"
    out = _share(_payload(item))
    assert "上游以后新加的东西" not in out
    assert "私密路径" not in out


def test_share_keywords_lists_exactly_what_appears():
    """⚠️ 探针关键词必须与默认断言句里的词不重叠——否则「它没出现」这条断言
    会被 canonical_text 里碰巧同名的字喂饱。"""
    payload = _payload(_insight("T1"),
                       _insight("T2", payload={"keywords": ["戊戌", "庚辛"],
                                               "doc_count": 3}))
    selections = {"T1": True, "T2": False}
    listed = share_keywords(payload, selections)
    assert listed == ["排版", "typography"]
    out = render_share(payload, selections)
    for kw in listed:
        assert kw in out
    assert "戊戌" not in out


def test_share_has_no_reference_constructs_either():
    out = _share(_payload(_insight("T1"), _corpus("C1")))
    for construct in ("src=", "href=", "<script", "@import", "url(", "<form"):
        assert construct not in out, construct


def test_share_escapes_too():
    item = _insight("T1")
    item["payload"]["keywords"] = ["<script>alert(1)</script>"]
    assert "<script>alert" not in _share(_payload(item))


# ---------------- 「零生成式文案」这条合同的牙齿 ----------------

def _visible_text(html: str) -> list[str]:
    """页面上人能读到的文字片段（去标签、去空白）。"""
    import re

    body = html.split("<body>", 1)[1]
    return [t for t in (s.strip() for s in re.sub(r"<[^>]+>", "\n", body).split("\n"))
            if t]


def _traceable(payload, *, share=False):
    """所有**允许**出现的文字：模板常量 + 能追溯到 payload 的片段。"""
    from kb_init.report import NEXT_STEP_HEADING, NEXT_STEP_TEXT, SHARE_DISCLOSURE

    allowed = {"你的知识库", "一份知识库报告", "读入的篇数 → 留下的篇数",
               NEXT_STEP_HEADING, NEXT_STEP_TEXT, SHARE_DISCLOSURE}
    allowed |= {title for _, title in [("topic", "主题"), ("residual", "碎片区"),
                                       ("corpus", "语料")]}
    for item in payload["insights"]:
        allowed.add(item["canonical_text"])
        allowed.add(item["insight_id"])
        p = item.get("payload") or {}
        allowed |= {str(k) for k in (p.get("keywords") or [])}
        if p.get("total") is not None and p.get("kept") is not None:
            allowed.add(f"{p['total']} → {p['kept']}")
        if not share and (p.get("evidence_titles") or []):
            allowed.add("证据：" + " · ".join(
                " ".join(str(t).split()) for t in p["evidence_titles"]))
    return allowed


def test_private_report_contains_no_generated_prose():
    """报告里每一句人能读到的话，要么是模板常量，要么能追溯到 payload。

    「断言句逐字出现」只证明该在的在了，证明不了**没有多出来的**——
    一个偷偷加上「你今年最痴迷的是 X」的实现，在那条断言下照样全绿。
    这条才是「零生成式文案」的牙齿。
    """
    payload = _payload(_insight("T1"), _insight("T2"),
                       _insight("R1", family="residual", kind="fragment_zone",
                                payload={"count": 637},
                                canonical_text="637 篇没有形成主题"),
                       _corpus("C1"))
    extra = [t for t in _visible_text(render_private(payload))
             if t not in _traceable(payload)]
    assert extra == [], f"报告里有追溯不到来源的文字：{extra}"


def test_share_report_contains_no_generated_prose():
    payload = _payload(_insight("T1"), _corpus("C1"))
    extra = [t for t in _visible_text(render_share(payload, _all_checked(payload)))
             if t not in _traceable(payload, share=True)]
    assert extra == [], f"分享版里有追溯不到来源的文字：{extra}"


def test_the_no_prose_detector_actually_catches_prose():
    """负例的配对正例：给 payload 塞一句谁也追溯不到的话，检测器必须抓住它。

    否则一个「_visible_text 永远返回空列表」的实现也能让上面两条全绿。
    """
    payload = _payload(_insight("T1", canonical_text="你今年最痴迷的是设计史"))
    extra = [t for t in _visible_text(render_private(payload))
             if t not in _traceable(_payload(_insight("T1")))]
    assert extra, "检测器没抓住一句捏造的文案"
