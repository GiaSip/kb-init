"""人工验收：把每条 topic 洞察的关键词与证据标题打出来，人判断认不认得出。

不进 CI，也不写任何断言——「簇认得出」是人工验收标准，拿自动断言冒充它，
等于用一个恒真的检查换掉真正的验收。

输出含真实笔记标题，只在本机看，不要把输出提交进仓库。

用法：
    .venv/bin/python probes/insight_quality_probe.py <kb-out 目录>
"""
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1])
    try:
        payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        print(f"找不到产物：{exc}", file=sys.stderr)
        return 1

    titles = {d["doc_id"]: d["title"] for d in manifest["documents"]}
    topics = [i for i in payload["insights"] if i["family"] == "topic"]

    print(f"分析项 {len(index['analyses'])} 个"
          f"（>1 表示有过大簇被细分）｜呈现级主题 {len(topics)} 条"
          f"｜总洞察 {payload['counts']['total']} 条\n")

    for item in topics:
        p = item["payload"]
        print(f"[{item['insight_id']}] {' · '.join(p['keywords']) or '（无关键词）'}"
              f"  — {p['doc_count']} 篇 / 占 kept {100 * p['share_of_kept']:.1f}%")
        for doc_id in p["evidence_doc_ids"]:
            print(f"      {titles.get(doc_id, '?')}")
        print()

    for item in payload["insights"]:
        if item["family"] != "topic":
            print(f"[{item['insight_id']}] {item['canonical_text']}")
    print()

    truncated = payload["presentation"]["truncated"]
    if truncated["shown"] != truncated["total"]:
        print(f"⚠️ 截断：显示 {truncated['shown']} / 共 {truncated['total']} 个主题，"
              f"未列出的覆盖 {truncated['omitted_docs']} 篇\n")

    print("回头条件（收据，不改变任何运行时行为）：")
    for c in payload["revisit_gate"]["conditions"]:
        extra = f"  ← {c['reason']}" if c.get("reason") else ""
        print(f"  {c['id']:22s} {c['state']:14s} "
              f"observed={c['observed']} threshold={c['threshold']}"
              f" → {c['prescription']}{extra}")

    print(f"\n请人工判断：上面每组关键词，认得出是什么主题吗？"
          f"（验收线：≥70%，即 {len(topics)} 组里至少 {-(-len(topics) * 7 // 10)} 组）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
