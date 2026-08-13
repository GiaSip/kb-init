#!/usr/bin/env python3
"""KB 诊断指标原型探针 — 只读，跑在贾老师自己的 Obsidian Wiki 上，验证指标有没有杀伤力"""
import os, re, time, collections, statistics

ROOT = os.path.expanduser("~/Documents/Obsidian Vault/Wiki")
EXCLUDE = {"_archive", "_claude-memory"}
NOW = time.time()
DAY = 86400

docs = {}          # relpath -> meta
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE and not d.startswith(".")]
    for fn in filenames:
        if not fn.endswith(".md"):
            continue
        full = os.path.join(dirpath, fn)
        rel = os.path.relpath(full, ROOT)
        try:
            text = open(full, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        st = os.stat(full)
        domain = rel.split(os.sep)[0] if os.sep in rel else "(根目录)"
        sub = os.sep.join(rel.split(os.sep)[:2]) if rel.count(os.sep) >= 1 else rel
        docs[rel] = {
            "stem": os.path.splitext(fn)[0],
            "chars": len(text),
            "age_days": (NOW - st.st_mtime) / DAY,
            "domain": domain,
            "sub": sub,
            "has_fm": text.startswith("---"),
            "text": text,
        }

# ---- 入链统计 ----
stem_index = collections.defaultdict(list)
for rel, m in docs.items():
    stem_index[m["stem"]].append(rel)

inlinks = collections.Counter()
broken = 0
total_links = 0
WIKILINK = re.compile(r"\[\[([^\]\|#]+)")
MDLINK = re.compile(r"\]\(([^)]+?\.md)\)")

for rel, m in docs.items():
    targets = set()
    for mt in WIKILINK.findall(m["text"]):
        targets.add(("wiki", mt.strip()))
    for mt in MDLINK.findall(m["text"]):
        targets.add(("md", os.path.basename(mt).replace(".md", "")))
    for kind, t in targets:
        total_links += 1
        hits = stem_index.get(t)
        if hits:
            for h in hits:
                if h != rel:
                    inlinks[h] += 1
        else:
            broken += 1

N = len(docs)
orphans = [r for r in docs if inlinks[r] == 0]
stale180 = [r for r in docs if docs[r]["age_days"] > 180]
stale365 = [r for r in docs if docs[r]["age_days"] > 365]
no_fm = [r for r in docs if not docs[r]["has_fm"]]
stubs = [r for r in docs if docs[r]["chars"] < 500]

dom_count = collections.Counter(d["domain"] for d in docs.values())
sub_count = collections.Counter(d["sub"] for d in docs.values())
lonely_subs = [k for k, v in sub_count.items() if v <= 2]
top3 = sum(c for _, c in dom_count.most_common(3))

print(f"=== 语料 ===")
print(f"总篇数 {N} | 总字符 {sum(d['chars'] for d in docs.values()):,} | 链接总数 {total_links}")
print()
print(f"=== 候选指标 ===")
print(f"孤儿率（无任何入链 = 存进去后再没被引用过）  {len(orphans)/N:.0%}  ({len(orphans)}/{N})")
print(f"平均入链数                                  {statistics.mean(inlinks[r] for r in docs):.2f}")
print(f"中位入链数                                  {statistics.median(inlinks[r] for r in docs):.0f}")
print(f"陈旧率 >180 天未动                          {len(stale180)/N:.0%}  ({len(stale180)})")
print(f"陈旧率 >365 天未动                          {len(stale365)/N:.0%}  ({len(stale365)})")
print(f"断链数（指向不存在的文档）                   {broken}  占链接 {broken/max(total_links,1):.0%}")
print(f"无 frontmatter（AI 拿不到元数据）            {len(no_fm)/N:.0%}  ({len(no_fm)})")
print(f"残桩率 <500 字符                            {len(stubs)/N:.0%}  ({len(stubs)})")
print()
print(f"=== 域集中度 ===")
print(f"top3 域占比 {top3/N:.0%}")
for k, v in dom_count.most_common(8):
    print(f"  {v:>4}  {k}")
print(f"孤儿子域（≤2 篇的二级目录）{len(lonely_subs)} 个 / 共 {len(sub_count)} 个二级目录")
print()
print(f"=== 组合指标草案：AI 可读性 ===")
readable = [r for r in docs
            if docs[r]["has_fm"] and docs[r]["chars"] >= 500
            and docs[r]["age_days"] <= 365 and inlinks[r] > 0]
print(f"同时满足「有元数据 + 非残桩 + 一年内动过 + 至少被引用一次」的: {len(readable)/N:.0%} ({len(readable)}/{N})")
