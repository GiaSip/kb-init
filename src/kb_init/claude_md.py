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


Grouped = list[tuple[str, list[dict]]]


def select_for_archive(payload: dict, selections: dict[str, bool]) -> Grouped:
    """只收「勾了」且「声明了去向」的条目，按 SECTIONS 分节。

    节序由 SECTIONS 决定，节内序等于 `insights` 数组序——**不重排**
    （沿用 2B「group_refs 有序，下游不得自行重排」的同一条纪律）。
    """
    by_section: dict[str, list[dict]] = {}
    for item in payload["insights"]:
        route = item["claude_md"]
        if route is None:
            continue
        if selections.get(item["insight_id"]) is not True:
            continue
        by_section.setdefault(route["section"], []).append(item)

    grouped = [(sid, by_section[sid]) for sid, _, _ in SECTIONS if by_section.get(sid)]
    if not grouped:
        raise ArchiveEmptyError(
            "没有任何条目能进档案：勾选的条目要么没被勾上，要么只进 Wrapped "
            "（语料层统计对 agent 无用）。一份空档案落在知识库根目录，"
            "agent 会当真读它，等于宣布「你没有关注领域」——所以这里什么都不写。")
    return grouped


def verify_canonical_texts(grouped: Grouped) -> None:
    """对**进档案的每一条**断言 render(payload) == canonical_text。

    双载合同要防的是「渲染器一升级，compile 就编译出用户从没审过的文字」。
    只校验进档案的那几条：corpus 族的文案与档案无关，让它挡住用户是无谓的严格。
    """
    from kb_init.insights import Insight, render

    for _, items in grouped:
        for item in items:
            insight = Insight(item["insight_id"], item["family"], item["kind"],
                              item["payload"], "")
            try:
                expected = render(insight)
            except (KeyError, TypeError) as exc:
                raise ArchiveContractError(
                    f"{item['insight_id']} 的 kind「{item['kind']}」"
                    f"本版渲染器算不出来（{exc}）——这份 insights.json 不是"
                    f"当前版本产出的，请用当前版本重跑一次。") from exc
            if expected != item["canonical_text"]:
                raise ArchiveContractError(
                    f"{item['insight_id']} 的 canonical_text 与 payload 对不上。"
                    f"档案里必须是用户审过的那句话，而这一句不是——"
                    f"请用当前版本重跑一次。")


ARCHIVE_TITLE = "# 关于这个知识库"
_GENERATED_NOTE = "<!-- 由 kb-init compile 生成，来自用户逐条确认过的洞察清单。 -->"


def identity_marker(payload: dict) -> str:
    """档案头部的出处标记。**它不是覆盖授权的依据**——授权走回执 + 内容哈希。
    把授权建立在一行印在产物里的标记上，等于把钥匙印在门上。"""
    return (f"<!-- kb-init:claude_md run_id={payload['run_id']} "
            f"corpus_hash={payload['corpus_hash']} "
            f"schema_version={payload['schema_version']} -->")


def render_archive(payload: dict, grouped: Grouped) -> str:
    """正文**逐字**是 canonical_text。

    2D 若拿 payload 自己排一句更好看的话，2D 的渲染器升级会犯和 2B 一模一样的病
    ——只是把病从上游挪到了下游。能加的只有结构与静态常量导语。
    """
    lines = [ARCHIVE_TITLE, "", identity_marker(payload), _GENERATED_NOTE, ""]
    leads = {sid: lead for sid, _, lead in SECTIONS}
    headings = {sid: heading for sid, heading, _ in SECTIONS}

    for section_id, items in grouped:
        lines += [f"## {headings[section_id]}", ""]
        if leads[section_id]:
            lines += [f"> {leads[section_id]}", ""]
        for item in items:
            lines.append(f"- {item['canonical_text']}")
            titles = (item.get("payload") or {}).get("evidence_titles") or []
            if titles:
                shown = " · ".join(
                    " ".join((t or "").split()) or "（无标题）" for t in titles)
                lines.append(f"  证据：{shown}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


RECEIPT_NAME = "compile.json"
LOCK_NAME = ".kb-init-compile.lock"
ARCHIVE_DIR = "knowledge"
ARCHIVE_NAME = "CLAUDE.md"
RECEIPT_SCHEMA_VERSION = "0.1"


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _read_receipt(out_dir) -> dict | None:
    import json

    try:
        receipt = json.loads((out_dir / RECEIPT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return receipt if isinstance(receipt, dict) else None


def _write_receipt(out_dir, payload: dict, digest: str, insight_ids: list[str]) -> None:
    import json
    import os

    from kb_init import __version__

    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "run_id": payload["run_id"],
        "corpus_hash": payload["corpus_hash"],
        "tool_version": __version__,
        "archive_path": f"{ARCHIVE_DIR}/{ARCHIVE_NAME}",
        "archive_sha256": digest,
        "insight_ids": list(insight_ids),
    }
    tmp = out_dir / f".{RECEIPT_NAME}.tmp"
    tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, out_dir / RECEIPT_NAME)


def _authorize(target, out_dir, payload: dict) -> None:
    """三条全满足才允许替换：回执在且 run_id 一致 / 现存文件哈希等于回执所记 /
    目标不是符号链接。

    授权不看产物里那行出处标记——它印在产物里，谁都能复制。
    """
    if target.is_symlink():
        raise ArchiveOverwriteError(
            f"{target} 是一个符号链接。绝不跟随符号链接写——那能把任意路径"
            f"变成写入目标。删掉它再重跑。")
    if not target.exists():
        return

    receipt = _read_receipt(out_dir)
    if receipt is None:
        raise ArchiveOverwriteError(
            f"{target} 已经存在，但 {out_dir / RECEIPT_NAME} 里没有本工具写过它的"
            f"记录——它可能是你自己的一篇笔记。拒绝覆盖。确认不要之后删掉它再重跑。")
    if receipt.get("run_id") != payload["run_id"]:
        raise ArchiveOverwriteError(
            f"{target} 是另一次运行（{receipt.get('run_id')}）写下的，"
            f"本次是 {payload['run_id']}。拒绝覆盖。")
    try:
        actual = _sha256(target.read_bytes())
    except OSError as exc:
        raise ArchiveOverwriteError(f"读不了 {target}（{exc}），拒绝覆盖。") from exc
    if actual != receipt.get("archive_sha256"):
        raise ArchiveOverwriteError(
            f"{target} 自上次生成之后被改动过。那是你的编辑，不该被无声抹掉——"
            f"拒绝覆盖。想重新生成就先删掉它。")


def publish(out_dir, payload: dict, text: str, insight_ids: list[str]):
    """授权 → 原子写档案 → 写回执。返回档案路径。

    顺序是「先档案后回执」：两个文件做不到共同原子，就把失败留在信息量最小的
    地方。回执写失败时**档案保留**（失败不许带走已完成的产物），代价是下次
    compile 会拒绝覆盖它——诊断里说清楚，不给它开后门。
    """
    import os
    from pathlib import Path

    out_dir = Path(out_dir)
    archive_dir = out_dir / ARCHIVE_DIR
    if not archive_dir.is_dir():
        # 不创建：能走到 compile 就说明流水线跑完过，knowledge/ 本来就该在。
        # 造一个只装着档案、没有任何知识的 knowledge/，是在造一个撒谎的产物。
        raise OSError(
            f"找不到 {archive_dir}（或它不是目录）。档案要和清洗产物放在一起，"
            f"而这个目录本该由上一步生成——请确认 -o 指的是完整的输出目录。")

    lock = out_dir / LOCK_NAME
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        # 不做超时自动清锁：「等久了就当它死了」是典型的兜底路径，
        # 而残锁的正确处置是人看一眼再删。
        raise OSError(
            f"另一个 compile 正在这个目录里运行（锁文件 {lock}）。"
            f"确认没有之后，删掉这个锁文件再重跑。") from exc
    os.close(fd)

    target = archive_dir / ARCHIVE_NAME
    tmp = archive_dir / f".{ARCHIVE_NAME}.tmp"
    try:
        _authorize(target, out_dir, payload)
        data = text.encode("utf-8")
        tmp.write_bytes(data)
        try:
            if target.exists():
                os.replace(tmp, target)
            else:
                # 新建走 link：原子且独占——「检查时不存在」与「创建」之间
                # 不留窗口，别的进程抢先建了就会抛而不是被我们覆盖。
                os.link(tmp, target)
                tmp.unlink()
        finally:
            tmp.unlink(missing_ok=True)
        _write_receipt(out_dir, payload, _sha256(data), insight_ids)
    finally:
        lock.unlink(missing_ok=True)
    return target
