"""L2 洞察层：把索引的事实编译成人能逐条勾选的洞察。

三族（topic / residual / corpus）不是为了好看：若所有洞察平等计数，回头条件
就会被 corpus 族的统计条目填满而永不触发。人肉 gate 的 12–20 上限按总条数算，
回头条件按 topic 族条数算。
"""
from __future__ import annotations

from dataclasses import dataclass, field

GroupRef = tuple[str, str]

ATTACHMENT_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".svg",
                       ".heic", ".mov", ".mp4", ".m4a", ".zip", ".csv", ".xlsx",
                       ".doc", ".docx", ".key", ".numbers", ".pages")


@dataclass(frozen=True)
class Insight:
    insight_id: str
    family: str
    kind: str
    payload: dict
    canonical_text: str
    evidence: dict = field(default_factory=lambda: {"doc_ids": [], "stat": None})
    claude_md: dict | None = None


def _members_by_group(analysis: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a in analysis["assignments"]:
        for m in a["memberships"]:
            out.setdefault(m["group_id"], []).append(a["doc_id"])
    return out


def _analysis(index: dict, analysis_id: str) -> dict:
    return next(a for a in index["analyses"] if a["analysis_id"] == analysis_id)


def presentation_groups(index: dict) -> list[GroupRef]:
    """呈现级 group = 未被细分的 group + 全部子分析的 group。

    这条规则只在这里实现一次。让 2C / 2D / 2E 各自解释 analyses 数组，
    三个下游必然长出三套不一致的解释。
    """
    subdivided = {
        (a["input_scope"]["analysis_id"], a["input_scope"]["group_id"])
        for a in index["analyses"][1:]
        if a["input_scope"].get("kind") == "parent_group"
    }
    sized: list[tuple[int, GroupRef]] = []
    for analysis in index["analyses"]:
        members = _members_by_group(analysis)
        for group in analysis["groups"]:
            ref = (analysis["analysis_id"], group["group_id"])
            if ref in subdivided:
                continue
            sized.append((len(members.get(group["group_id"], [])), ref))
    # 篇数降序；同篇数按 ref 升序，保证顺序确定
    return [ref for _, ref in sorted(sized, key=lambda t: (-t[0], t[1]))]


def group_members(index: dict, ref: GroupRef) -> list[str]:
    return sorted(_members_by_group(_analysis(index, ref[0])).get(ref[1], []))


def effective_residual_ids(index: dict) -> list[str]:
    """这次运行实际没有主题的文档 = 不属于任何**呈现级** group 的 kept 文档。

    不能简单地取「各分析 residual 的并集减去被 assigned 过的」：父簇被细分之后，
    它在 analyses[0] 里的那个 assigned 已经作废，那些文档若在子分析里落回
    residual，它们就是真的没有主题。定义必须挂在 presentation_groups 上，
    两个函数才不会各说各话。

    analyses[0] 一个字节都没改——「折回 residual」是这里派生出来的，
    不是回头去编辑第一轮的结果。
    """
    root = index["analyses"][0]
    all_kept = {a["doc_id"] for a in root["assignments"]}
    covered: set[str] = set()
    for ref in presentation_groups(index):
        covered.update(group_members(index, ref))
    return sorted(all_kept - covered)


def _pct(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.1f}%" if whole else "0.0%"


def build_corpus_insights(manifest: dict, index: dict) -> list[Insight]:
    """语料层事实。条件不成立的一律不产出——不给「你有 0 篇重复文档」这种条目。

    全部 claude_md=None：留存率、断链数对 agent 无用，进 CLAUDE.md 只是噪音。
    """
    counts = manifest["counts"]
    root = index["analyses"][0]
    out: list[Insight] = []
    seq = 0

    def add(kind: str, payload: dict, text: str, stat: dict) -> None:
        nonlocal seq
        seq += 1
        out.append(Insight(f"C{seq}", "corpus", kind, payload, text,
                           {"doc_ids": [], "stat": stat}, None))

    total, kept = counts["total"], counts["kept"]
    add("retention",
        {"total": total, "kept": kept, "dropped_stub": counts["dropped_stub"],
         "dropped_duplicate": counts["dropped_duplicate"]},
        f"读入 {total} 篇，留下 {kept} 篇（{_pct(kept, total)}）；"
        f"{counts['dropped_stub']} 篇是空壳",
        {"total": total, "kept": kept})

    time_axis = root["time_axis"]
    if not time_axis["available"]:
        add("date_blindness",
            {"dated_docs": time_axis["dated_docs"],
             "total_docs": time_axis["total_docs"],
             "coverage": time_axis["coverage"], "threshold": time_axis["threshold"]},
            f"只有 {time_axis['dated_docs']} 篇能确定时间"
            f"（{_pct(time_axis['dated_docs'], time_axis['total_docs'])}）——"
            f"导出包里就没带时间戳，所以这份报告里没有任何时间轴洞察",
            {"coverage": time_axis["coverage"]})

    links = manifest.get("unresolved_links") or []
    if links:
        by_kind = {"attachment": 0, "document": 0}
        for link in links:
            target = (link.get("target") or "").lower()
            key = "attachment" if target.endswith(ATTACHMENT_SUFFIXES) else "document"
            by_kind[key] += 1
        add("broken_refs", {"total": len(links), "by_kind": by_kind},
            f"有 {len(links)} 处引用指向不存在的目标"
            f"（附件 {by_kind['attachment']} / 文档 {by_kind['document']}）",
            {"total": len(links)})

    if counts["dropped_duplicate"]:
        add("exact_duplicates", {"count": counts["dropped_duplicate"]},
            f"{counts['dropped_duplicate']} 篇内容完全相同，已合并",
            {"count": counts["dropped_duplicate"]})

    return out
