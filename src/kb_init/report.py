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
