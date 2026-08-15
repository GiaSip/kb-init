"""`insights.md` 的**唯一**真源：渲染、解析、校验都在这里。

渲染与解析拆成两个模块、由两处各写一半，是格式漂移最经典的来源；
放在同一个模块里，round-trip 测试才拦得住。

用户**只应该改 `[x]` / `[ ]`**。正文一律不被信任——compile 按 ID 从 json 取。
"""
from __future__ import annotations

import re

_HEADER = re.compile(
    r"<!--\s*kb-init:run_id=(?P<run_id>\S+)\s+corpus_hash=(?P<corpus_hash>\S+)"
    r"\s+schema_version=(?P<schema_version>\S+)\s*-->"
)
_ITEM = re.compile(r"^- \[(?P<mark>[x ])\] `(?P<id>[A-Za-z]+\d+)`")
# 只用来给出**有针对性的报错**，绝不用来放宽解析。用户把 `[x]` 写成 `[X]`、
# 或给行加了缩进时，严格正则会整行跳过，最后报「清单里缺少 T2」——那句话
# 会让用户以为自己删了东西，实际是勾选框写法不对。
_ITEM_LOOSE = re.compile(r"^\s*[-*]?\s*\[(?P<mark>.?)\]\s*`(?P<id>[A-Za-z]+\d+)`")

_SECTIONS = (("topic", "主题"), ("residual", "碎片区"), ("corpus", "语料"))


class InsightsValidationError(ValueError):
    """校验失败一律 fail closed，且必须带行号——「有一条对不上」而不说哪一条，
    用户只能全文肉眼比对。"""


def render_markdown(payload: dict) -> str:
    lines = [
        "# kb-init — 洞察确认清单",
        "",
        f"<!-- kb-init:run_id={payload['run_id']} "
        f"corpus_hash={payload['corpus_hash']} "
        f"schema_version={payload['schema_version']} -->",
        "",
        "> 只改 `[x]` / `[ ]`。改正文不会生效——`compile` 按 ID 从 insights.json 取正文。",
        "> 改完跑 `kb-init compile`，或先跑 `kb-init validate insights.md` 单独校验。",
        "",
    ]
    by_family: dict[str, list[dict]] = {}
    for item in payload["insights"]:
        by_family.setdefault(item["family"], []).append(item)

    for family, title in _SECTIONS:
        items = by_family.get(family, [])
        if not items:
            continue
        lines += [f"## {title}（{len(items)} 条）", ""]
        for item in items:
            lines.append(f"- [x] `{item['insight_id']}` {item['canonical_text']}")
            titles = (item.get("payload") or {}).get("evidence_titles") or []
            if titles:
                shown = " · ".join(
                    " ".join((t or "").split()) or "（无标题）" for t in titles
                )
                lines.append(f"      证据：{shown}")
        lines.append("")

    truncated = (payload.get("presentation") or {}).get("truncated") or {}
    if truncated and truncated.get("shown") != truncated.get("total"):
        # 只写「12 个主题」而隐去遗漏，才是制造虚假完整性
        lines += [
            f"> ⚠️ 主题按篇数展示前 {truncated['shown']} 个，共 {truncated['total']} 个；"
            f"未列出的 {truncated['total'] - truncated['shown']} 个覆盖 "
            f"{truncated['omitted_docs']} 篇（完整清单见 insights.json）。",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def parse_markdown(text: str) -> dict:
    header = _HEADER.search(text)
    selections: dict[str, bool] = {}
    for line in text.splitlines():
        match = _ITEM.match(line)
        if match:
            selections[match.group("id")] = match.group("mark") == "x"
    return {
        "run_id": header.group("run_id") if header else None,
        "corpus_hash": header.group("corpus_hash") if header else None,
        "schema_version": header.group("schema_version") if header else None,
        "selections": selections,
    }


def validate_markdown(text: str, payload: dict) -> None:
    header = _HEADER.search(text)
    if header is None:
        raise InsightsValidationError(
            "头部标记缺失或被改坏：找不到 <!-- kb-init:run_id=… --> 那一行。"
            "请用本次运行产出的 insights.md 重新开始。"
        )
    if header.group("run_id") != payload["run_id"]:
        raise InsightsValidationError(
            f"run_id 不匹配：文件是 {header.group('run_id')}，"
            f"insights.json 是 {payload['run_id']}——这是两次不同运行的产物。"
        )
    if header.group("corpus_hash") != payload["corpus_hash"]:
        raise InsightsValidationError(
            f"corpus_hash 不匹配：文件是 {header.group('corpus_hash')}，"
            f"insights.json 是 {payload['corpus_hash']}——语料已经变了。"
        )

    known = {i["insight_id"] for i in payload["insights"]}
    seen: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _ITEM.match(line)
        if not match:
            loose = _ITEM_LOOSE.match(line)
            if loose and loose.group("id") in known:
                raise InsightsValidationError(
                    f"第 {lineno} 行：{loose.group('id')} 的勾选框格式不对。"
                    f"只认 `- [x] ` 与 `- [ ] `——不能缩进，`x` 必须小写，"
                    f"横线与方括号之间要有一个空格。"
                )
            continue
        insight_id = match.group("id")
        if insight_id in seen:
            raise InsightsValidationError(
                f"第 {lineno} 行：ID {insight_id} 重复"
                f"（首次出现在第 {seen[insight_id]} 行）"
            )
        if insight_id not in known:
            raise InsightsValidationError(
                f"第 {lineno} 行：未知 ID {insight_id}，insights.json 里没有这一条"
            )
        seen[insight_id] = lineno

    missing = sorted(known - set(seen))
    if missing:
        raise InsightsValidationError(
            f"清单里缺少这些 ID：{'、'.join(missing)}。"
            "绝不静默少编几条——请用本次运行产出的 insights.md 重新开始。"
        )
