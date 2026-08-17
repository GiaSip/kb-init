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
#
# 中文的阈值单独放低一位：四字词（项目代号、成语式命名）在中文里既常见又独特，
# 而四个字母的英文词满地都是。用同一个数字卡两种文字，等于在其中一种上做错。
MIN_LEN = 5
MIN_LEN_CJK = 4

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
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{4,}")
# 窗长取 4 而不是 6：**短窗比长窗更灵敏**。仓库里若引用了一个 6 字短语，
# 它必然包含某个 4 字窗，于是 4 字探针照样命中；反过来则不成立——
# 只生成 6 字窗时，一句被摘走的 4 字词组谁也抓不到。
# 代价是噪音变多，而噪音由人扫一眼解决，漏报没人解决。
_CJK_WINDOW = 4
_CJK = re.compile(r"[\u4e00-\u9fff]")
# 「词字符连续段」：中英数混排的术语（形如字母 + 汉字连写）既不是空白分词的产物，
# 连续汉字段又常常不够长，两条路都覆盖不到它——而这类词恰恰最独特。
_WORDRUN = re.compile(r"\w+", re.UNICODE)


# 两端都要剥：只剥右侧的话，`(Falcon)` 会变成 `(Falcon`，而仓库里那个裸的
# `Falcon` 照样查不到——**假绿**。弯引号同理，它们在中文文案里比直引号常见。
_EDGE_PUNCT = ".,;:!?()[]{}<>\"'“”‘’（）【】「」『』，。；：！？·、…-—~`*_/\\"


def _trim(word: str) -> str:
    return word.strip(_EDGE_PUNCT)


def _fragments(text: str) -> set[str]:
    out = {text} if len(text) >= MIN_LEN else set()
    # 按空白切出来的词常带着附着标点（`Falcon,`）。拿它原样去查，
    # 仓库里那个不带逗号的 `Falcon` 就永远查不到——**假绿**。
    for word in map(_trim, text.split()):
        out.add(word)
        # 意语的省音写法（撇号连写）只按空白切的话，只会得到整体，
        # 而仓库里摘的往往是撇号后面那个实词。按撇号再拆一次，增量小、噪音低。
        if "'" in word or "\u2019" in word:
            out.update(_trim(part) for part in re.split(r"['\u2019]", word))
    for url in _URL.findall(text):
        out.add(url)
        # 也单独放主机名：实际漏出去的那次，仓库里留的就是 URL 的一部分。
        # 主机名要按 / ? # 一起切，并剥掉尾随标点：`https://host?q=1` 只按 "/"
        # 切会得到 `host?q=1`，那个串在仓库里永远查不到——**漏报**。
        host = re.split(r"[/?#]", url.split("//", 1)[-1], maxsplit=1)[0]
        host = _trim(host)
        if len(host) >= MIN_LEN:
            out.add(host)
    # **只收含汉字的混排段**。不加这个限制的话，`\w+` 会把 URL 碎片（https、
    # cloud）和标题里的普通英文词全放进来——实测真命中 5 条、噪音 9 条，
    # 而「全是噪音时人会直接忽略它」正是这个脚本开头写着的失效模式。
    # 纯拉丁的段落本来就由空白分词那条路覆盖，这里补的只是它覆盖不到的混排词。
    out.update(w for w in _WORDRUN.findall(text) if _CJK.search(w))
    for run in _CJK_RUN.findall(text):
        out.add(run)
        # 长段要切**逐字滑窗**，不是不重叠地跳着切：仓库里引用的常常只是半句，
        # 而人从哪个字开始摘是任意的。步长等于窗长的话，凡是跨窗口边界的那半句
        # 就永远生不成探针——那是一条稳定的假绿路径，而它看起来完全正常。
        for i in range(len(run) - _CJK_WINDOW + 1):
            out.add(run[i:i + _CJK_WINDOW])
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
    def long_enough(word: str) -> bool:
        floor = MIN_LEN_CJK if _CJK.search(word) else MIN_LEN
        return len(word) >= floor

    return {p for p in out
            if long_enough(p) and p.lower() not in GENERIC and not p.isdigit()}


class ProbeError(RuntimeError):
    """git 本身出错。**必须抛，不能当作"没命中"**——一个把错误读成干净的
    检查器比没有检查器更糟：它会在你最需要它的那次给你一个绿灯。"""


def _json_escaped(needle: str) -> str | None:
    """`json.dumps` 默认 `ensure_ascii=True` 时，非 ASCII 字符在文件里长成
    `\\u4f73\\u8d24` 那样。拿解码后的原文去 grep，那类文件里的泄露一个都查不出来
    ——而这个仓库的测试 fixture 就有用默认参数写 json 的。

    两处容易写错，都会造成假绿：

    1. **只转 ASCII 之外的那些字符**。含中文时把整串（包括英文字母）都转成
       `\\u0068` 这种形式，得到的串在任何真实 JSON 里都不存在，等于白查。
    2. **触发条件是「有没有非 ASCII 字符」，不是「有没有汉字」**。这份语料是
       中英意三语，带变音符的拉丁词（形如 `caf` + `\\u00e9`）按汉字判就根本不生成
       转义形式。

    ⚠️ 顺带一条：**别把语料风格的词写进这个文件当例子**——写进来它就成了下一个
    命中源，而检查器自己刷屏会让人开始忽略它的输出。上面那个例子是拆开写的。
    """
    if needle.isascii():
        return None
    return "".join(c if c.isascii() else f"\\u{ord(c):04x}" for c in needle)


def hits(needle: str) -> list[str]:
    found = []
    escaped = _json_escaped(needle)
    if escaped:
        found += [f"{label}(JSON 转义形式): {line}"
                  for label, line in _scan(escaped)]
    found += [f"{label}: {line}" for label, line in _scan(needle)]
    return found


def _scan(needle: str) -> list[tuple[str, str]]:
    found = []
    for args, label in (
        # `-e` 与 `--` 都不是可选的：以 `-` 开头的探针词否则会被 git 当成选项，
        # 于是这个词永远查不出命中——而漏报正是这个脚本要防的东西。
        # `-i` 是因为大小写变体照样是泄露。
        # `--untracked` 不是可有可无：刚写完还没 `git add` 的文件，
        # `git grep` 默认根本不看——而"我刚在测试里贴了段真实内容"正是最常见的
        # 那一刻。少这一个开关，这个脚本在最该报警的时候会说干净。
        (["git", "grep", "-l", "-i", "-F", "--untracked", "-e", needle, "--"],
         "工作树"),
        # 暂存区单独查一遍：内容已 `git add`、工作树又被清干净时，
        # 只查工作树会报「干净」，然后它跟着下一次提交进历史。
        (["git", "grep", "-l", "-i", "-F", "--cached", "-e", needle, "--"], "暂存区"),
        # ⚠️ `-i` / `--regexp-ignore-case` **对 `-S` 不生效**——它只作用于
        # `--grep` 那类正则匹配。要让 pickaxe 忽略大小写，必须同时给
        # `--pickaxe-regex`，并把探针词按正则转义（否则 `.` `?` 会被当元字符，
        # 那又是另一种漏报）。
        (["git", "log", "--all", "--oneline", "-i", "--pickaxe-regex",
          f"-S{re.escape(needle)}"], "历史(diff)"),
        # commit message 也是仓库内容，而且**会被 GitHub 全文索引**。
        # `-S` 只看文件差异，看不见提交信息——这一条不查，把真实标题写进
        # commit message 的那种泄露就永远报干净。
        # ⚠️ 这里用 `-F` 而不是 re.escape：`--grep` 走的是 **git 自己的**正则，
        # Python 的转义风格喂进去会因为括号不配对直接 exit 128
        # （实测撞到过；当时没有默默报干净，是因为上一轮加了返回码检查）。
        (["git", "log", "--all", "--oneline", "-i", "-F",
          f"--grep={needle}"], "历史(commit message)"),
    ):
        result = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
        # git grep / git log 的 1 是「没找到」，其余非零是真错误。
        if result.returncode not in (0, 1):
            raise ProbeError(
                f"{label}查询失败（exit {result.returncode}）："
                f"{result.stderr.strip()[:200]}")
        if result.stdout.strip():
            found.append((label, result.stdout.strip().splitlines()[0]))
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
    if not needles:
        # 一个探针都没取到时报「干净」，就是这个项目反复踩的那个形状：
        # 空集合让结论恒为真。真相是**这次检查根本没发生**。
        print("检查中止：一个探针词都没取到——给的文件可能不是 insights.json，"
              "或者它没有 keywords / evidence_titles。这不叫干净，叫没查。",
              file=sys.stderr)
        return 2
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
