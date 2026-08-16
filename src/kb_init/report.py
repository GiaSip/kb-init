"""Wrapped 报告的渲染层：payload → HTML 字符串。

**这个模块不碰磁盘。** 私有版由 `pipeline.py` 写进 staging（随 rename 一次发布），
分享版由 `cli.py` 在 compile 末尾原子写入。让渲染器自己写盘，就会出现第二套
原子性实现，而这个项目已经有一套审了七轮的了。

两条硬约束在这里落地：

1. **语料内容进 HTML 是真实攻击面**（DESIGN R13）。关键词与证据标题全部来自
   用户语料，而开源工具接受任意导出包。所有插值必须过 `esc()`。
2. **产物不许撒谎**。条形的长度必须从零起算、与篇数成正比——一条被截断坐标轴的
   柱子是在撒谎，只是撒得好看。
"""
from __future__ import annotations

import html
import math


class ReportContractError(ValueError):
    """渲染期的合同违例：payload 里的值渲染不出来。"""


def esc(value: str) -> str:
    """**唯一**的 HTML 转义入口。

    模板里不允许出现未经它的插值——转义散在多处，漏掉一处就是全部防线归零，
    而漏掉的那一处不会有任何症状。`quote=True` 覆盖 `"` 与 `'`，
    因为插值也会出现在属性上下文里。
    """
    return html.escape(value, quote=True)


def bar_width(part, whole) -> str:
    """条形宽度的百分比数值（不带 `%`），固定一位小数，钳位 `[0, 100]`。

    **这是整份报告里唯一进入 CSS 的值**，所以它是唯一需要防 CSS 注入的地方——
    HTML 转义保护不了 CSS 语法。判据不是「小心一点」而是可测的三条：
    只接受数字、钳位、固定格式。

    非有限值（NaN / inf）与非数字一律抛，**不静默取 0**：取 0 是猜，而且会画出
    一条与事实无关的柱子。
    """
    for name, value in (("part", part), ("whole", whole)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ReportContractError(
                f"条形的 {name} 不是数字：{value!r}。字符串一旦流进 style 属性"
                f"就是一个 CSS 注入面，所以这里不接受它。")
        if not math.isfinite(value):
            raise ReportContractError(f"条形的 {name} 不是有限数：{value!r}。")
    if whole <= 0:
        return "0.0"
    return f"{min(100.0, max(0.0, 100.0 * part / whole)):.1f}"


FAMILY_ORDER = (("topic", "主题"), ("residual", "碎片区"), ("corpus", "语料"))

NEXT_STEP_HEADING = "下一步"
NEXT_STEP_TEXT = (
    "打开同目录的 insights.md，把你不认可的条目从 [x] 改成 [ ]，"
    "然后跑 kb-init compile。只有你留下的条目会进入给 agent 用的档案。"
)

_CSP = ("default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'none'; base-uri 'none'")

# 无外链：字体只用系统族，配色写死在内联样式里。一个需要联网才好看的报告
# 不满足「双击打开、无需联网」，而那正是「能直接发给别人看」的前提。
_CSS = """
:root { color-scheme: light dark; }
body { margin: 0 auto; padding: 2.5rem 1.25rem 4rem; max-width: 46rem;
       font-family: -apple-system, "PingFang SC", "Segoe UI", sans-serif;
       line-height: 1.7; color: #1a1a1a; background: #fbfaf8; }
h1 { font-size: 1.4rem; font-weight: 600; margin: 0 0 .25rem; }
.headline { font-size: 3.2rem; font-weight: 700; letter-spacing: -.02em;
            margin: .5rem 0; }
.sub { color: #6b6660; font-size: .85rem; margin: 0 0 2.5rem; }
h2 { font-size: 1.05rem; margin: 2.5rem 0 1rem; padding-bottom: .4rem;
     border-bottom: 1px solid #e5e0d8; }
.card { padding: 1rem 0 1.2rem; border-bottom: 1px solid #efece7; }
.id { display: inline-block; font-family: ui-monospace, monospace;
      font-size: .72rem; color: #8a8378; border: 1px solid #ddd6cb;
      border-radius: 3px; padding: .05rem .35rem; margin-right: .5rem; }
.chip { display: inline-block; background: #ece7dd; border-radius: 999px;
        padding: .15rem .6rem; margin: .15rem .25rem .15rem 0;
        font-size: .9rem; font-weight: 600; }
.track { height: .5rem; background: #ece7dd; border-radius: 999px;
         margin: .7rem 0 .5rem; overflow: hidden; }
.fill { height: 100%; background: #b0472b; border-radius: 999px; }
.text { margin: .35rem 0 0; }
.evidence { color: #6b6660; font-size: .82rem; margin: .35rem 0 0; }
.next { margin-top: 3rem; padding: 1rem 1.2rem; background: #f2eee7;
        border-left: 3px solid #b0472b; }
.next p { margin: .3rem 0 0; }
.disclosure { color: #6b6660; font-size: .8rem; margin-top: 2.5rem; }
""".strip()


def _head(title: str) -> list[str]:
    return [
        "<!DOCTYPE html>",
        '<html lang="zh">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">',
        f"<title>{esc(title)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
    ]


def _by_family(insights: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for item in insights:
        out.setdefault(item.get("family", ""), []).append(item)
    return out


def _headline(insights: list[dict]) -> tuple[str, str]:
    """大字来自 retention 的 payload。没有这一条就不编——
    「620 → 287」是事实，编一个「你的知识库」是文案。"""
    for item in insights:
        if item.get("kind") == "retention":
            p = item["payload"]
            return f"{p['total']} → {p['kept']}", "读入的篇数 → 留下的篇数"
    return "", ""


def _chips(keywords) -> str:
    return "".join(f'<span class="chip">{esc(str(k))}</span>'
                   for k in (keywords or []))


def _evidence_line(titles) -> list[str]:
    if not titles:
        return []
    shown = " · ".join(" ".join(str(t).split()) or "（无标题）" for t in titles)
    return [f'<p class="evidence">证据：{esc(shown)}</p>']


def _card(item: dict, *, largest: int, with_evidence: bool) -> list[str]:
    payload = item.get("payload") or {}
    lines = ['<div class="card">',
             f'<span class="id">{esc(str(item["insight_id"]))}</span>'
             + _chips(payload.get("keywords"))]
    count = payload.get("doc_count", payload.get("count"))
    if isinstance(count, (int, float)) and not isinstance(count, bool):
        width = bar_width(count, largest)
        lines += ['<div class="track">'
                  f'<div class="fill" style="width: {width}%"></div></div>']
    lines.append(f'<p class="text">{esc(str(item["canonical_text"]))}</p>')
    if with_evidence:
        lines += _evidence_line(payload.get("evidence_titles"))
    lines.append("</div>")
    return lines


def _largest_count(insights: list[dict]) -> int:
    counts = [(i.get("payload") or {}).get("doc_count",
                                           (i.get("payload") or {}).get("count"))
              for i in insights]
    numeric = [c for c in counts
               if isinstance(c, (int, float)) and not isinstance(c, bool)]
    return max(numeric) if numeric else 0


def _body(insights: list[dict], *, with_evidence: bool) -> list[str]:
    """条目顺序 = insights 数组序，节序 = FAMILY_ORDER。呈现层不重排、不筛选。"""
    largest = _largest_count(insights)
    grouped = _by_family(insights)
    lines: list[str] = []
    for family, title in FAMILY_ORDER:
        items = grouped.get(family) or []
        if not items:
            continue
        lines.append(f"<h2>{esc(title)}</h2>")
        for item in items:
            lines += _card(item, largest=largest, with_evidence=with_evidence)
    return lines


def render_private(payload: dict) -> str:
    """给自己看的全量版：这就是 DESIGN §4.2 说的那个验收界面。

    **零生成式文案**：断言性文字一律是 canonical_text 逐字。报告与档案若说的不是
    同一句话，用户就是在用文案 A 做决定、而档案里进的是文案 B——那正是 2B 的
    双载合同要防的病，只是换成了「呈现层 vs 真源」这一对。
    """
    insights = payload.get("insights") or []
    big, sub = _headline(insights)
    lines = _head("kb-init — 你的知识库")
    lines.append("<h1>你的知识库</h1>")
    if big:
        lines += [f'<p class="headline">{esc(big)}</p>',
                  f'<p class="sub">{esc(sub)}</p>']
    lines += _body(insights, with_evidence=True)
    lines += ['<div class="next">',
              f"<strong>{esc(NEXT_STEP_HEADING)}</strong>",
              f"<p>{esc(NEXT_STEP_TEXT)}</p>",
              "</div>",
              "</body>", "</html>"]
    return "\n".join(lines) + "\n"
