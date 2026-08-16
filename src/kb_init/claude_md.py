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
    # 顶层与元字段也在这里验，而不是指望调用方先验过。CLI 确实先验了，
    # 但「模块自己不检查，靠上游帮它检查」正是「两个入口两套标准」的温床——
    # 下一个调用方（2C / 2E）不会知道它欠着这笔债。
    if not isinstance(payload, dict):
        raise ArchiveContractError("insights.json 的顶层不是对象。")
    for field in ("run_id", "corpus_hash", "schema_version"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise ArchiveContractError(
                f"insights.json 缺少可用的 {field}（{value!r}）——"
                f"没有它就无法确认这份档案出自哪一次运行。")

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
        if not isinstance(insight_id, str) or not insight_id:
            # 不先验类型的话，list / dict 型 ID 会在下一行的 `in seen` 上抛
            # 不可哈希的 TypeError——绕过退出码 9，直接给用户一段 traceback。
            raise ArchiveContractError(
                f"第 {n} 条洞察的 insight_id 不是非空字符串：{insight_id!r}。")
        if insight_id in seen:
            # 一个勾选框授权两段正文进档案：用户审的是一条，进去的是两条。
            raise ArchiveContractError(
                f"insights.json 里 ID {insight_id} 出现了不止一次——"
                f"一个勾选框会授权两段正文进档案。")
        seen.add(insight_id)

        _check_route(insight_id, item["claude_md"])
        _check_evidence_titles(insight_id, item["payload"])


def _check_evidence_titles(insight_id: str, payload) -> None:
    """证据标题必须是字符串列表。

    渲染时会对每个标题做空白折叠（`.split()`），元素若是数字就抛 AttributeError
    ——绕过退出码 9，直接给用户一段 traceback。**不做类型强转**：把 7 悄悄
    渲染成 "7" 是替上游猜它想说什么，而这里根本不知道那是标题还是别的什么。
    """
    if not isinstance(payload, dict):
        raise ArchiveContractError(f"{insight_id} 的 payload 不是对象。")
    titles = payload.get("evidence_titles")
    if titles is None:
        return
    if not isinstance(titles, list) or any(not isinstance(t, str) for t in titles):
        raise ArchiveContractError(
            f"{insight_id} 的 evidence_titles 不是字符串列表：{titles!r}。")


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
            except Exception as exc:
                # 捕获面必须宽：原先只抓 KeyError/TypeError，而 length_profile
                # 的 `:g` 格式化在坏 payload 上抛的是 ValueError——漏出去就是
                # 给普通用户一段 traceback。
                #
                # ⚠️ 措辞刻意**不下结论**。渲染器抛异常有两种可能：这份 json 是
                # 旧版产的，或者渲染器自己有 bug。原先的文案一口咬定是前者，
                # 那是在猜——而猜错的代价是把工具的 bug 伪装成用户的数据问题，
                # 让人去重跑一个永远跑不好的流程。
                raise ArchiveContractError(
                    f"算不出 {item['insight_id']}（kind={item['kind']}）的正文："
                    f"{type(exc).__name__}: {exc}。"
                    f"可能是这份 insights.json 不是当前版本产出的（用当前版本"
                    f"重跑一次即可），也可能是 kb-init 自己的缺陷——"
                    f"若重跑后仍然如此，请带着这条信息报 issue。") from exc
            if expected != item["canonical_text"]:
                raise ArchiveContractError(
                    f"{item['insight_id']} 的 canonical_text 与 payload 对不上。"
                    f"档案里必须是用户审过的那句话，而这一句不是——"
                    f"请用当前版本重跑一次。")


ARCHIVE_TITLE = "# 关于这个知识库"
GENERATED_NOTE = "<!-- 由 kb-init compile 生成，来自用户逐条确认过的洞察清单。 -->"


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
    lines = [ARCHIVE_TITLE, "", identity_marker(payload), GENERATED_NOTE, ""]
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


def _write_exclusive(path, data: bytes) -> None:
    """先 unlink 再 O_EXCL 建，绝不写进一个已经存在的路径。

    直接 `write_bytes` 会**跟随符号链接**：谁在 knowledge/ 里预置一个
    `.CLAUDE.md.tmp` 符号链接，我们就替他写坏了链接指向的文件。
    `unlink` 删的是链接本身而不是它指向的东西，所以这两步合起来既清掉了
    上次崩溃留下的残骸，也堵掉了这条写入通道。
    """
    import os

    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


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
    try:
        _write_exclusive(
            tmp, json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8"))
        os.replace(tmp, out_dir / RECEIPT_NAME)
    finally:
        # replace 失败时 tmp 会留下；下次运行虽然会先 unlink 它，但一个
        # 半成品文件躺在输出目录里本身就会让人误判发生了什么。
        tmp.unlink(missing_ok=True)


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
        # 「没有回执」有两种成因，拒绝的动作相同，但**诊断必须分开**：
        # 一种是这文件根本不是我们写的（很可能是用户自己的笔记），
        # 另一种是上一次运行在「作废旧回执」与「写新回执」之间失败了。
        # 后者说成「可能是你自己的笔记」是在冤枉用户，会让人不敢删自己的东西。
        #
        # ⚠️ 这里读那行出处标记**只为了把话说准**，不构成授权——
        # 两条分支都照样拒绝。标记可以被复制，所以它能证明的只有
        # 「这看起来像我们写的」，不能证明「这确实是我们写的」。
        marker = identity_marker(payload)
        try:
            looks_like_ours = marker in target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            looks_like_ours = False
        if looks_like_ours:
            raise ArchiveOverwriteError(
                f"{target} 带着本次运行的标记，但 {out_dir / RECEIPT_NAME} 不在了"
                f"——多半是上一次 compile 写完档案之后中途失败了。"
                f"确认这份档案的内容之后删掉它再重跑即可；"
                f"这里不替你决定，因为标记是可以被复制的，我无法确定它真是我写的。")
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


def check_archive_dir(out_dir) -> None:
    """`knowledge/` 必须已存在、是目录、且不是符号链接。

    **不创建**：能走到 compile 就说明流水线跑完过，这个目录本来就该在。
    造一个只装着档案、没有任何知识的 `knowledge/`，是在造一个撒谎的产物。

    这个检查单独暴露出来，是为了让 CLI 能在**进入任何洞察 gate 之前**先问一次
    ——否则「目录被删了」会先撞上「你一条都没勾」（8）或别的码，诊断指错方向。
    """
    from pathlib import Path

    archive_dir = Path(out_dir) / ARCHIVE_DIR
    if archive_dir.is_symlink():
        # 目标文件拒绝跟随符号链接，目录这一层同理——否则整份档案会被写到
        # 链接指向的地方去，而调用者以为它在输出目录里。
        raise OSError(
            f"{archive_dir} 是一个符号链接。档案不写进符号链接指向的目录——"
            f"请确认 -o 指的是 kb-init 自己生成的输出目录。")
    if not archive_dir.is_dir():
        raise OSError(
            f"找不到 {archive_dir}（或它不是目录）。档案要和清洗产物放在一起，"
            f"而这个目录本该由上一步生成——请确认 -o 指的是完整的输出目录。")


def publish(out_dir, payload: dict, text: str, insight_ids: list[str]):
    """授权 → 原子写档案 → 写回执。返回档案路径。

    顺序是「先档案后回执」：两个文件做不到共同原子，就把失败留在信息量最小的
    地方。回执写失败时**档案保留**（失败不许带走已完成的产物），代价是下次
    compile 会拒绝覆盖它——诊断里说清楚，不给它开后门。
    """
    import os
    from pathlib import Path

    out_dir = Path(out_dir)
    check_archive_dir(out_dir)
    archive_dir = out_dir / ARCHIVE_DIR

    lock = out_dir / LOCK_NAME
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        # 不做超时自动清锁：「等久了就当它死了」是典型的兜底路径，
        # 而残锁的正确处置是人看一眼再删。
        raise OSError(
            f"另一个 compile 正在这个目录里运行（锁文件 {lock}）。"
            f"确认没有之后，删掉这个锁文件再重跑。") from exc

    target = archive_dir / ARCHIVE_NAME
    tmp = archive_dir / f".{ARCHIVE_NAME}.tmp"
    try:
        # os.close 放进 try：它抛异常的概率极低，但放在外面就意味着
        # 「取到锁却没进 finally」这条路径存在，残锁要人工去删。
        os.close(fd)
        _authorize(target, out_dir, payload)
        data = text.encode("utf-8")
        try:
            # 写 tmp 放进这个 try：写到一半失败（磁盘满、被打断）同样会
            # 留下半份 .tmp，而残骸会让下一个人误判发生过什么。
            #
            # ⚠️ 顺序：**tmp 先写满，再作废回执，最后一步换文件。**
            # 上一版把「作废回执」放在写 tmp 之前，于是磁盘满这种常见故障会留下
            # {旧档案完好, 回执没了} —— 下次 compile 会以「没有回执」拒绝覆盖，
            # 并要求用户删掉一份**完好的、我们自己写的**档案。修一个撒谎的回执，
            # 修出了一个冤枉用户的诊断。
            _write_exclusive(tmp, data)
            # 作废旧回执。**不变量：回执存在 ⇒ 它描述的就是盘上那份档案。**
            # 不作废的话，「档案换成新的、回执写失败」会留下一份记着旧哈希的
            # 回执——它会（错误地）指控用户手改过档案，而其实是我们换的。
            (out_dir / RECEIPT_NAME).unlink(missing_ok=True)
            if target.exists():
                os.replace(tmp, target)
            else:
                # 新建走 link：原子且独占——「检查时不存在」与「创建」之间
                # 不留窗口，别的进程抢先建了就会抛而不是被我们覆盖。
                os.link(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        _write_receipt(out_dir, payload, _sha256(data), insight_ids)
    finally:
        lock.unlink(missing_ok=True)
    return target
