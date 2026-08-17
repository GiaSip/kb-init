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

**已知漏报面**（如实写明，不假装覆盖）：跨行切碎的字符串查不到——`git grep` 与
`git log -S` 都按行匹配。所以它不是"证明没泄露"，是"把最常见的那几类捞出来"。

退出码：0 干净 / 1 有命中（**需要人看**）/ 2 检查本身没跑成。
"""
from __future__ import annotations

import json
import re
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
           "claude", "content", "counter", "silicon", "another", "indesign",
           # 第二轮实跑之后补的。⚠️ 往这个表里加词是有代价的：加错一个，
           # 将来那个词真的泄露了也不会报。所以只加**词典词**与**产品名**，
           # 不加任何看起来像人名、账号名、项目代号的东西。
           # preposizione / grammatica 是意大利语的语法术语，2B 的合成 fixture
           # 拿它们测意语停用词过滤，与用户的笔记只是撞词。
           "preposizione", "grammatica", "account", "author", "profile",
           "claude code", "recovery", "toggle"}


_URL = re.compile(r"https?://[^\s\u3000）)】」』，。；]+")
# 连续 CJK 段：中文标题没有空格，只按空白切会得到「整句」一个探针，
# 而真实泄露往往是**片段**（引用半句、抄一个词组）。按标点切出连续 CJK 段，
# 每段本身就足够独特。漏报比误报危险得多，这里刻意偏向多产生候选。
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{5,}")


def _fragments(text: str) -> set[str]:
    out = {text} if len(text) >= MIN_LEN else set()
    out.update(w for w in text.split() if len(w) >= MIN_LEN)
    for url in _URL.findall(text):
        out.add(url)
        # 也单独放主机名：实际漏出去的那次，仓库里留的就是 URL 的一部分。
        host = url.split("//", 1)[-1].split("/", 1)[0]
        if len(host) >= MIN_LEN:
            out.add(host)
    out.update(_CJK_RUN.findall(text))
    return out


def probes(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("insights", []):
            body = item.get("payload") or {}
            for kw in body.get("keywords") or []:
                out |= _fragments(str(kw))
            for title in body.get("evidence_titles") or []:
                out |= _fragments(str(title))
    return {p for p in out
            if len(p) >= MIN_LEN and p.lower() not in GENERIC and not p.isdigit()}


class ProbeError(RuntimeError):
    """git 本身出错。**必须抛，不能当作"没命中"**——一个把错误读成干净的
    检查器比没有检查器更糟：它会在你最需要它的那次给你一个绿灯。"""


def hits(needle: str) -> list[str]:
    found = []
    for args, label in (
        # `-e` 与 `--` 都不是可选的：以 `-` 开头的探针词否则会被 git 当成选项，
        # 于是这个词永远查不出命中——而漏报正是这个脚本要防的东西。
        # `-i` 是因为大小写变体照样是泄露。
        (["git", "grep", "-l", "-i", "-F", "-e", needle, "--"], "工作树"),
        (["git", "log", "--all", "--oneline", "--regexp-ignore-case",
          f"-S{needle}"], "历史"),
    ):
        result = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
        # git grep / git log 的 1 是「没找到」，其余非零是真错误。
        if result.returncode not in (0, 1):
            raise ProbeError(
                f"{label}查询失败（exit {result.returncode}）："
                f"{result.stderr.strip()[:200]}")
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
    try:
        leaked = {n: h for n in sorted(needles) if (h := hits(n))}
    except ProbeError as exc:
        print(f"检查中止：{exc}", file=sys.stderr)
        return 2
    if not leaked:
        print("✅ 仓库与历史里没有真实语料内容")
        return 0
    print(f"❌ {len(leaked)} 个探针词出现在仓库里：")
    for needle, where in leaked.items():
        print(f"  {needle!r} → {'；'.join(where)}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
