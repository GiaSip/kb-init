"""档案线：把用户勾选过的洞察编译成他的知识库的 `CLAUDE.md`。

⚠️ 这里产出的 `CLAUDE.md` 是**给用户的 agent 读的档案**，与本仓库根目录那份
（kb-init 自己的项目上下文）是两个东西。

这一层是**纯管道**：节数由上游 `claude_md.section` 决定，本模块既不合成内容、
也不含「哪条洞察该进哪一节」的知识。2E 接上时新增几节，这里一行都不用改——
但**认不出的 section 必须炸**，见 `check_structure`。
"""
from __future__ import annotations

# (section_id, 标题, 导语)
#
# 导语只能陈述**对任何语料都成立的管道事实**。初稿写的是「这不是稳定性排序——
# 这份语料里能确定时间的文档太少」，后半句是关于**这份**语料的事实却被写死成了
# 常量：换一份 time_axis 可用的语料，它立刻变成假话。产物不许撒谎这条，
# 对写死的常量同样成立。
SECTIONS: tuple[tuple[str, str, str | None], ...] = (
    ("focus_areas", "关注领域", "按篇数排序。"),
    ("coverage", "这份档案的覆盖范围", None),
)

KNOWN_SECTIONS = frozenset(s[0] for s in SECTIONS)

REQUIRED_INSIGHT_KEYS = ("insight_id", "family", "kind", "payload",
                         "canonical_text", "claude_md")


class ArchiveContractError(ValueError):
    """`insights.json` 与本版代码对不上（CLI 映射为退出码 9）。

    修复动作在工具手上（用当前版本重跑），不在用户手上——所以它绝不能被
    报成 7（「你手上这份清单不合法」），那会把用户支去改一份没有问题的文件。
    """


class ArchiveEmptyError(ValueError):
    """没有任何条目能进档案线（退出码 8）。修复动作在用户手上：回去勾几条。"""


class ArchiveOverwriteError(ValueError):
    """目标文件存在且未获覆盖授权（退出码 1）。"""


def check_structure(payload: dict) -> None:
    """扫**全量** insights，与勾选状态无关。不合格即抛。

    ⚠️ 这个函数刻意不接收 selections。若路由校验晚于「按勾选过滤」，
    一条本版不认识的 section 只要用户没勾就会安静流过全部检查——
    直到某天他勾了才炸；更糟的是当它恰好是唯一能进档案的一族时，
    管道会走到「没有可归档条目」而报出 8，把原因说成用户没勾选。
    这是「留一条兜底路径，规则就被它绕过」的第七种形态。
    """
    insights = payload.get("insights")
    if not isinstance(insights, list):
        raise ArchiveContractError(
            "insights.json 的 insights 不是数组——这份文件不是本工具产出的洞察真源。")

    seen: set[str] = set()
    for n, item in enumerate(insights, start=1):
        if not isinstance(item, dict):
            raise ArchiveContractError(f"第 {n} 条洞察不是对象。")
        missing = [k for k in REQUIRED_INSIGHT_KEYS if k not in item]
        if missing:
            raise ArchiveContractError(
                f"第 {n} 条洞察缺少字段：{'、'.join(missing)}。")

        insight_id = item["insight_id"]
        if insight_id in seen:
            # 一个勾选框授权两段正文进档案：用户审的是一条，进去的是两条。
            raise ArchiveContractError(
                f"insights.json 里 ID {insight_id} 出现了不止一次——"
                f"一个勾选框会授权两段正文进档案。")
        seen.add(insight_id)

        _check_route(insight_id, item["claude_md"])


def _check_route(insight_id: str, claude_md) -> None:
    if claude_md is None:
        return
    if not isinstance(claude_md, dict):
        raise ArchiveContractError(
            f"{insight_id} 的 claude_md 既不是 null 也不是对象。")
    if set(claude_md) != {"section"}:
        # 多余键同样拒绝：形状对不上就是对不上。放行「多带了个键」等于
        # 默许上游偷偷加语义，而下游对它一无所知。
        raise ArchiveContractError(
            f"{insight_id} 的 claude_md 应当恰好只有 section 一个键，"
            f"实际是 {sorted(claude_md)}。")
    section = claude_md["section"]
    if not isinstance(section, str) or not section:
        raise ArchiveContractError(
            f"{insight_id} 的 section 不是非空字符串：{section!r}。")
    if section not in KNOWN_SECTIONS:
        raise ArchiveContractError(
            f"{insight_id} 声明要进「{section}」这一节，但本版 kb-init 不认识它"
            f"（认识的是 {sorted(KNOWN_SECTIONS)}）。"
            f"认不出就不输出会让这一节静默消失，而没人会来报「我的档案少了一节」"
            f"——请用当前版本重跑一次。")
