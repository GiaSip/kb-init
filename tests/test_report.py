"""Wrapped 报告：呈现层。

这一层的两条硬约束都在这里落地：语料内容进 HTML 是真实攻击面（DESIGN R13），
以及「产物不许撒谎」——一条被截断坐标轴的柱子就是在撒谎。
"""
import pytest

from kb_init.report import ReportContractError, bar_width, esc


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
