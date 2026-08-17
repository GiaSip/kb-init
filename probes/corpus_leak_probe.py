#!/usr/bin/env python3
"""开源卫生：检查真实语料的内容有没有漏进仓库（含 git 历史）。

`git grep "/Users/…"` 那条检查抓的是**路径**，抓不到**内容**——而实际漏出去的
恰恰是内容：写 spec 时随手引一个真实的关键词、造测试 fixture 时从真实产物里
抄一条 URL。两次都发生过，且都是在「我知道要注意开源卫生」的前提下发生的。
所以这件事需要一个检测器，不能靠记得。

**探针字符串来自仓库外的真实产物，本脚本自身不含任何个人数据**——
否则检查器就成了下一个泄露源。

    python3 probes/corpus_leak_probe.py ~/path/to/insights.json [更多...]

**命中是线索不是判决。** 一个来自语料的普通词碰巧出现在文档里，与"语料内容漏了"
是两回事——所以这是**发布前的人工检查项，不是 CI 门**：它把候选列出来，由人扫一眼。
把它做成自动门的话，噪音会逼着后来的人加豁免，而豁免清单迟早会把真命中也豁免掉。

退出码：0 干净 / 1 有命中（**需要人看**，不等于一定有问题）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 太短或太通用的词会把整个仓库都命中，那样的检查等于没有检查
# （全是噪音时人会直接忽略它，和恒返回脏是同一个病）。
MIN_LEN = 5

# 这些词虽然来自语料，但它们本来就是通用技术词，出现在仓库里与语料无关。
GENERIC = {"design", "architecture", "layout", "settings", "template", "command",
           "feedback", "users", "email", "choose", "short", "leave", "includes",
           "learn", "keep", "card", "grey", "life", "real", "feel", "great",
           "quotes", "highlight", "responsive", "framing", "garment", "diffused",
           "intentions", "happenings", "grateful", "personality", "captions",
           # 实跑一次之后补的：这些词命中仓库与语料无关（Claude 是模型名，
           # Content 来自 Content-Security-Policy，Counter 是 Python 类，
           # Silicon 来自 README 的 Apple Silicon，another 在内置停用词表里）。
           "claude", "content", "counter", "silicon", "another", "indesign"}


def probes(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("insights", []):
            body = item.get("payload") or {}
            for kw in body.get("keywords") or []:
                out.add(str(kw))
            for title in body.get("evidence_titles") or []:
                # 标题整句太长且常带标点，按空白切成词再筛
                out.update(str(title).split())
    return {p for p in out
            if len(p) >= MIN_LEN and p.lower() not in GENERIC and not p.isdigit()}


def hits(needle: str) -> list[str]:
    found = []
    for args, label in (
        (["git", "grep", "-l", "-F", needle], "工作树"),
        (["git", "log", "--all", "-S", needle, "--oneline"], "历史"),
    ):
        result = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
        if result.stdout.strip():
            found.append(f"{label}: {result.stdout.strip().splitlines()[0]}")
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    paths = [Path(a).expanduser() for a in argv]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"找不到：{missing}", file=sys.stderr)
        return 2

    needles = probes(paths)
    print(f"从 {len(paths)} 份产物取到 {len(needles)} 个探针词")
    leaked = {n: h for n in sorted(needles) if (h := hits(n))}
    if not leaked:
        print("✅ 仓库与历史里没有真实语料内容")
        return 0
    print(f"❌ {len(leaked)} 个探针词出现在仓库里：")
    for needle, where in leaked.items():
        print(f"  {needle!r} → {'；'.join(where)}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
