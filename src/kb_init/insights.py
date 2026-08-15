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


TOPIC_INSIGHT_CAP = 12
LONG_ORPHAN_MIN_RESIDUAL = 3
LONG_ORPHAN_SHOW = 3
EVIDENCE_SHOW = 3

_RENDERERS: dict = {}


def _renderer(kind: str):
    def deco(fn):
        _RENDERERS[kind] = fn
        return fn
    return deco


def render(insight: Insight) -> str:
    """`canonical_text` 的**唯一**生成器。

    payload 与 canonical_text 双载是为了让 compile 拿到的正是用户审过的那句话；
    双载就必须有一个地方保证两者等价，就是这里。
    """
    return _RENDERERS[insight.kind](insight.payload)


@_renderer("topic_cluster")
def _render_topic(p: dict) -> str:
    # 措辞纪律：产出的是关键词不是主题名。写成「你的主题是 X」就是产物在撒谎——
    # 单语言簇上它给出的可能只是那门语言的通用词。
    return (f"这 {p['doc_count']} 篇里最具区分度的词是 "
            f"{' · '.join(p['keywords']) if p['keywords'] else '（没有足够区分度的词）'}"
            f" — 占 kept {100 * p['share_of_kept']:.1f}%")


@_renderer("fragment_zone")
def _render_fragment(p: dict) -> str:
    return f"{p['count']} 篇没有形成主题（占 kept {100 * p['share_of_kept']:.1f}%）"


@_renderer("long_orphans")
def _render_long_orphans(p: dict) -> str:
    return (f"碎片区里篇幅最大的 {len(p['evidence_doc_ids'])} 篇还没长成主题"
            f"（最长 {p['longest_chars']} 字）")


def _with_text(insight: Insight) -> Insight:
    return Insight(
        insight_id=insight.insight_id,
        family=insight.family,
        kind=insight.kind,
        payload=insight.payload,
        canonical_text=render(insight),
        evidence=insight.evidence,
        claude_md=insight.claude_md,
    )


def _evidence_docs(index: dict, ref: GroupRef, members: list[str]) -> list[str]:
    """代表优先取 medoid，不足则按 doc_id 补齐——顺序必须确定。"""
    group = next(g for g in _analysis(index, ref[0])["groups"]
                 if g["group_id"] == ref[1])
    picked = [r["doc_id"] for r in group.get("representatives", [])
              if r["doc_id"] in members]
    for d in members:
        if len(picked) >= EVIDENCE_SHOW:
            break
        if d not in picked:
            picked.append(d)
    return picked[:EVIDENCE_SHOW]


def build_topic_insights(
    index: dict, bodies: dict[str, str], titles: dict[str, str], kept_count: int
) -> tuple[list[Insight], dict]:
    from kb_init.keywords import extract_keywords

    refs = presentation_groups(index)
    shown = refs[:TOPIC_INSIGHT_CAP]
    omitted = refs[TOPIC_INSIGHT_CAP:]

    members_of = {ref: group_members(index, ref) for ref in refs}
    keywords = extract_keywords(
        bodies, {f"{a}|{g}": members_of[(a, g)] for a, g in refs}
    )

    out: list[Insight] = []
    for n, ref in enumerate(shown, start=1):
        members = members_of[ref]
        evidence = _evidence_docs(index, ref, members)
        payload = {
            "group_ref": {"analysis_id": ref[0], "group_id": ref[1]},
            "keywords": keywords[f"{ref[0]}|{ref[1]}"],
            "doc_count": len(members),
            "share_of_kept": round(len(members) / kept_count, 6) if kept_count else 0.0,
            "evidence_doc_ids": evidence,
            "evidence_titles": [titles.get(d, "") for d in evidence],
        }
        out.append(_with_text(Insight(
            f"T{n}", "topic", "topic_cluster", payload, "",
            {"doc_ids": evidence, "stat": None}, {"section": "focus_areas"})))

    # 只写「12 个主题」而隐去遗漏，才是制造虚假完整性。截断本身不说谎。
    truncated = {
        "shown": len(shown),
        "total": len(refs),
        "omitted_group_refs": [{"analysis_id": a, "group_id": g} for a, g in omitted],
        "omitted_docs": sum(len(members_of[r]) for r in omitted),
    }
    return out, truncated


def build_residual_insights(
    index: dict, bodies: dict[str, str], titles: dict[str, str], kept_count: int
) -> list[Insight]:
    residual = effective_residual_ids(index)
    if not residual:
        return []

    out = [_with_text(Insight(
        "R1", "residual", "fragment_zone",
        {"count": len(residual),
         "share_of_kept": round(len(residual) / kept_count, 6) if kept_count else 0.0},
        "", {"doc_ids": [], "stat": {"count": len(residual)}}, None))]

    # 纯按长度排序，**不做任何归属**——「这几篇贴着某个主题的边」是 halo 判断，
    # 不落 membership 字段也仍然是软归属，那属于方案 C 的范围。
    #
    # 不用「长度进入前 X 分位」这种判据：residual 占 77–84% 是这类语料的常态，
    # 分位点本身就被 residual 主导，阈值怎么取都会退化成恒真或恒假（实测两种都撞过）。
    # 改成无阈值的「碎片区里篇幅最大的几篇」——不可能空洞，也没有魔数。
    if len(residual) >= LONG_ORPHAN_MIN_RESIDUAL:
        ranked = sorted(residual, key=lambda d: (-len(bodies.get(d, "")), d))
        evidence = ranked[:LONG_ORPHAN_SHOW]
        longest = len(bodies.get(evidence[0], ""))
        if longest:
            out.append(_with_text(Insight(
                "R2", "residual", "long_orphans",
                {"residual_count": len(residual), "longest_chars": longest,
                 "evidence_doc_ids": evidence,
                 "evidence_titles": [titles.get(d, "") for d in evidence]},
                "", {"doc_ids": evidence, "stat": {"longest_chars": longest}}, None)))
    return out


SCHEMA_VERSION = "0.1"
GATE_RULES_VERSION = "2b-1"
INSUFFICIENT_TOPICS_THRESHOLD = 4
TOPICS_CONCENTRATED_THRESHOLD = 2
RESIDUAL_HIGH_THRESHOLD = 0.70
INSIGHT_FILES = ("insights.json", "insights.md")


def build_revisit_gate(
    topic_count: int,
    presentation_group_count: int,
    residual_share: float,
    corpus_is_first_party: bool = True,
) -> dict:
    """回头条件的**收据**，不是开关：触发不改变任何运行时行为。

    2B 只供数、不自授裁决权——`state` 由本函数按 rules_version 记录的规则算出，
    是可复现的记录，供下一次人类决策使用。

    第三条只在**非本人语料**上可判。拿本人的第二份语料冒充它通过，
    正是这条回头条件想防的自证。

    ⚠️ 判据是 **topic 族条数**，不是洞察总数。按总数算的话，corpus 族的统计条目
    会把数量填满，①永远为假——这个项目已经有三轮「留一条兜底路径，规则就被
    它绕过」的事故史。
    """
    def cond(cid, threshold, observed, triggered, prescription, not_evaluable=None):
        item = {"id": cid, "threshold": threshold, "observed": observed,
                "state": "triggered" if triggered else "not_triggered",
                "prescription": prescription}
        if not_evaluable:
            item["state"] = "not_evaluable"
            item["reason"] = not_evaluable
        return item

    return {
        "rules_version": GATE_RULES_VERSION,
        "inputs": {
            "topic_insight_count": topic_count,
            "presentation_group_count": presentation_group_count,
            "residual_share": round(residual_share, 6),
            "corpus_is_first_party": corpus_is_first_party,
        },
        "conditions": [
            cond("insufficient_topics", INSUFFICIENT_TOPICS_THRESHOLD, topic_count,
                 topic_count < INSUFFICIENT_TOPICS_THRESHOLD, "subdivide"),
            cond("topics_concentrated", TOPICS_CONCENTRATED_THRESHOLD,
                 presentation_group_count,
                 presentation_group_count <= TOPICS_CONCENTRATED_THRESHOLD,
                 "subdivide"),
            cond("residual_high", RESIDUAL_HIGH_THRESHOLD, round(residual_share, 6),
                 residual_share > RESIDUAL_HIGH_THRESHOLD, "halo",
                 not_evaluable="requires_third_party_corpus"
                 if corpus_is_first_party else None),
        ],
    }


def build_insight_set(
    index: dict,
    manifest: dict,
    bodies: dict[str, str],
    titles: dict[str, str],
    *,
    corpus_is_first_party: bool = True,
) -> dict:
    from dataclasses import asdict

    from kb_init import __version__
    from kb_init.keywords import DEFAULT_PARAMS

    kept = manifest["counts"]["kept"]
    topics, truncated = build_topic_insights(index, bodies, titles, kept)
    residual = build_residual_insights(index, bodies, titles, kept)
    corpus = build_corpus_insights(manifest, index)
    items = [*topics, *residual, *corpus]

    families = [i.family for i in items]
    refs = presentation_groups(index)
    residual_share = len(effective_residual_ids(index)) / kept if kept else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": index["run_id"],
        "corpus_hash": index["corpus_hash"],
        "index_schema_version": index["schema_version"],
        "versions": {"kb_init": __version__},
        "naming": {"method": DEFAULT_PARAMS["method"],
                   "params": {k: v for k, v in DEFAULT_PARAMS.items()
                              if k != "method"}},
        "presentation": {
            "group_refs": [{"analysis_id": a, "group_id": g} for a, g in refs],
            "truncated": truncated,
        },
        # counts 由数组派生。独立计数迟早与数组漂移，而漂移没有症状。
        "counts": {"topic": families.count("topic"),
                   "residual": families.count("residual"),
                   "corpus": families.count("corpus"),
                   "total": len(items)},
        "revisit_gate": build_revisit_gate(
            families.count("topic"), len(refs), residual_share,
            corpus_is_first_party),
        "insights": [asdict(i) for i in items],
    }


def write_insights(out_dir, payload: dict, markdown: str) -> None:
    """洞察子事务：两个文件要么都发布，要么都不发布。

    只有 md 没有 json，用户会对着一份永远 validate 不过的清单勾选。
    """
    import json
    from pathlib import Path

    out_dir = Path(out_dir)
    try:
        (out_dir / "insights.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "insights.md").write_text(markdown, encoding="utf-8")
    except BaseException:
        cleanup_insight_files(out_dir)
        raise


def cleanup_insight_files(out_dir) -> None:
    """逐个独立尝试——连续 unlink 时第一个失败会中断第二个，
    留下的恰恰是最危险的半份产物。"""
    from pathlib import Path

    for name in INSIGHT_FILES:
        try:
            (Path(out_dir) / name).unlink(missing_ok=True)
        except OSError:
            pass


def insight_files_remain(out_dir) -> bool:
    from pathlib import Path

    return any((Path(out_dir) / name).exists() for name in INSIGHT_FILES)
