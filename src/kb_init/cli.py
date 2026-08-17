import argparse
import sys
import zipfile
from pathlib import Path

from kb_init import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kb-init",
        description="把笔记导出编译成 AI 能用的知识库",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--wikilinks",
        action="store_true",
        help="输出 [[wikilink]] 方言（默认输出标准相对路径链接）",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="跳过索引：不下载模型、不联网，几秒拿到清洗产物",
    )
    parser.add_argument(
        "--corpus-provenance",
        choices=("unknown", "first-party", "third-party"),
        default="unknown",
        help="这份语料属于谁：unknown（默认）/ first-party（自己的）/ "
             "third-party（别人的）。只有 third-party 才会评估「residual 过高」"
             "这条回头条件——工具无从自己判断，默认成 first-party 会让它永远不触发",
    )
    parser.add_argument("source", nargs="?", help="导出文件夹或 zip 路径")
    parser.add_argument("-o", "--out", default="kb-out", help="输出目录（默认 kb-out）")
    return parser


class _BundleError(Exception):
    """洞察三件套（insights.md / insights.json / manifest.json）配不成对。"""


def _locate_bundle(md: Path) -> dict:
    """`validate` 与 `compile` **共用**的配对定位与 manifest gate。

    两个读取入口必须是同一套标准：只要有一个入口对 manifest 网开一面，
    「清理失败时留下的半份产物不算数」这条规则就会被它绕过。所以这段逻辑
    只存在一份，两个命令都从这里进。
    """
    import json

    if not md.exists():
        raise _BundleError(f"找不到 {md}")
    json_path = md.with_name("insights.json")
    if not json_path.exists():
        raise _BundleError(f"同目录下找不到 insights.json（{json_path}）。"
                           f"需要两份文件配对。")
    # 清理失败时我们刻意把半份产物留在盘上（为了不牵连完好的清洗产物），
    # 那笔账记在 manifest 里——读取入口不去问，这条兜底就形同虚设。
    manifest_path = md.with_name("manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        status = manifest["insights_status"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # 缺失 / 损坏 / 没这个字段 / 顶层不是对象（`[]`、`null`、字符串——
        # 下标会抛 TypeError），四种都拒绝，不「读不到就跳过」。
        raise _BundleError(
            f"读不到 {manifest_path} 里的 insights_status（{exc}），"
            f"无法确认这两份文件算不算数。它们必须与 manifest 放在一起。") from exc
    if status != "complete":
        raise _BundleError(
            f"manifest 说这次运行的洞察状态是 {status!r}，不是 complete"
            f"——这两份文件可能是残留或半成品，拒绝使用。")
    return {"json_path": json_path, "manifest": manifest}


def _validate_command(md_path: str) -> int:
    """`kb-init validate <insights.md>`：独立校验勾选清单与它的 json 真源。

    退出码 7 而不是复用 6：6 是「这次运行的洞察没生成」，7 是「你手上这份清单
    不合法」，下一步动作完全不同（重跑 vs 改文件）。
    """
    import json

    from kb_init.insights_md import InsightsValidationError, validate_markdown

    md = Path(md_path)
    try:
        bundle = _locate_bundle(md)
    except _BundleError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 7
    try:
        payload = json.loads(bundle["json_path"].read_text(encoding="utf-8"))
        validate_markdown(md.read_text(encoding="utf-8"), payload)
    except InsightsValidationError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 7
    except (OSError, ValueError, KeyError) as exc:
        print(f"错误：读取失败——{exc}", file=sys.stderr)
        return 7
    print(f"校验通过：{len(payload['insights'])} 条洞察全部对得上。")
    return 0


SHARE_REPORT_NAME = "report.share.html"


def _write_share_report(out_dir: Path, html: str) -> Path:
    """原子写入 out_dir 根目录。不套档案那套覆盖授权，理由见调用处。

    **先删旧的再写新的**：这一步是隐私要求，不是洁癖。写失败时若把上一次的
    分享版留在标准路径上，用户以为那是最新的就发出去了——而他这次取消勾选的
    条目还在里面。宁可没有，也不能留一份「他以为已经撤掉了」的分享版。

    tmp 用随机名（`mkstemp`）：固定名会让两个并发的 compile 互删对方的临时文件，
    有可能发布出半写的 HTML；随机名 + 原子 replace 则最差也只是「谁后写谁赢」，
    而分享版是可重新生成的派生品，这个结果可以接受。
    """
    import os
    import tempfile

    target = out_dir / SHARE_REPORT_NAME
    target.unlink(missing_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{SHARE_REPORT_NAME}.", dir=out_dir)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(html.encode("utf-8"))
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def _warn_if_stale_share_report(out_dir: Path) -> None:
    """compile 没能产出新的分享版时，提醒用户目录里还躺着旧的那份。

    **不删**：那是上一次成功运行的完好产物，删它撞「失败不许带走已完成的产物」。
    但也不能不说：分享版是**专门用来发出去**的，而它反映的是上一次的勾选——
    用户取消勾选之后 compile 报了错，他很可能以为「那份已经不算数了」。
    档案没有这个问题（它给本机的 agent 读），分享版有。
    """
    if (out_dir / SHARE_REPORT_NAME).exists():
        print(f"注意：{out_dir / SHARE_REPORT_NAME} 还是**上一次**生成的，"
              f"反映的是上一次的勾选。这次没有产出新的分享版——"
              f"发出去之前请确认它是你想要的那一版，或者先删掉它。",
              file=sys.stderr)


def _compile_command(md_path: str) -> int:
    """把 `_compile` 包起来，**在唯一的出口**统一提醒旧分享版。

    早先只在退出码 8 / 1 两处提醒，而 4 / 7 / 9 同样会留下上一次的分享版——
    提醒漏了一半等于没提醒：用户偏偏会在报错那次以为「这次没生成，那份还是旧的吧」，
    也偏偏可能不这么想。放在唯一出口才不会漏。
    """
    code = _compile(md_path)
    if code != 0:
        _warn_if_stale_share_report(Path(md_path).parent)
    return code


def _compile(md_path: str) -> int:
    """`kb-init compile <insights.md>`：把勾选过的洞察编译成知识库的 CLAUDE.md。

    gate 顺序不是随便排的（2D spec §5）：**版本与身份 gate 必须早于
    validate_markdown**。否则一份旧的或来自另一次运行的 insights.json 会被报成
    7「你手上这份清单不合法」，把用户支去改一份根本没有问题的文件——
    7 的修复动作在用户手上，9 的在工具手上，报错码指错方向，人就会做错事。

    **结构 gate 必须早于按勾选过滤**，理由见 claude_md.check_structure。
    """
    import json

    from kb_init.claude_md import (
        ArchiveContractError,
        ArchiveEmptyError,
        ArchiveOverwriteError,
        check_archive_dir,
        check_structure,
        publish,
        render_archive,
        select_for_archive,
        verify_canonical_texts,
    )
    from kb_init.insights import SCHEMA_VERSION
    from kb_init.insights_md import (
        InsightsValidationError,
        parse_markdown,
        validate_markdown,
    )

    md = Path(md_path)
    try:
        # **第一个** gate，早于 manifest：目录被删掉时若拖到后面才发现，
        # 用户会先看到「manifest 对不上」（7）、「你一条都没勾」（8）或
        # 「json 对不上」（9）——诊断指向完全错误的方向。
        # 「这个目录根本不是一个 kb-init 输出目录」是最结构性的那个事实，
        # 它该先说。
        check_archive_dir(md.parent)
    except OSError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 4
    try:
        bundle = _locate_bundle(md)
    except _BundleError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 7

    manifest = bundle["manifest"]
    try:
        try:
            payload = json.loads(bundle["json_path"].read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # compile 的码空间比 validate 细：读不动的 json 不是「你的清单不合法」，
            # 是「这份真源不能用」，修复动作是重跑。
            raise ArchiveContractError(
                f"读不了 {bundle['json_path']}（{exc}）。") from exc
        if not isinstance(payload, dict):
            raise ArchiveContractError("insights.json 的顶层不是对象。")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ArchiveContractError(
                f"insights.json 是 schema {payload.get('schema_version')!r}，"
                f"本版 kb-init 认的是 {SCHEMA_VERSION!r}——"
                f"两者不是同一版格式，请用当前版本重跑一次。")
        for field in ("run_id", "corpus_hash"):
            got = payload.get(field)
            # 只比相等是不够的：两边**同时缺失**时 None == None 会放行，
            # 而后面 identity_marker 取 payload["run_id"] 会裸抛 KeyError
            # ——用户拿到的是一段 traceback，不是诊断。
            # 「两边都没有」不等于「两边一致」，那是拿缺失当共识。
            if not isinstance(got, str) or not got:
                raise ArchiveContractError(
                    f"insights.json 里没有可用的 {field}（{got!r}）——"
                    f"这份文件缺少身份，无法确认它属于哪一次运行。")
            if manifest.get(field) != got:
                raise ArchiveContractError(
                    f"manifest 的 {field} 是 {manifest.get(field)!r}，"
                    f"insights.json 是 {got!r}——"
                    f"这两份文件不是同一次运行的产物。")
        check_structure(payload)
    except ArchiveContractError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 9

    try:
        text_md = md.read_text(encoding="utf-8")
        validate_markdown(text_md, payload)
    except InsightsValidationError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 7
    except OSError as exc:
        print(f"错误：读不了 {md}——{exc}", file=sys.stderr)
        return 4

    selections = parse_markdown(text_md)["selections"]
    try:
        from kb_init.report import ReportContractError, render_share, share_keywords

        grouped = select_for_archive(payload, selections)
        verify_canonical_texts(grouped)
        # 两份都先在内存里渲染完：渲染失败时一个字节都还没落盘。
        archive_text = render_archive(payload, grouped)
        share_html = render_share(payload, selections)
        keywords = share_keywords(payload, selections)

        archive = publish(
            md.parent, payload, archive_text,
            [i["insight_id"] for _, items in grouped for i in items])
        # 分享版落 out_dir 根目录，那里 100% 是工具自有产物（语料只进 knowledge/，
        # 且 out_dir 非空时主 run 直接拒绝运行）——碰撞面不存在，所以不给它套
        # 档案那套覆盖授权。为一个不存在的风险加机制，本身就是一种谎。
        try:
            share_path = _write_share_report(md.parent, share_html)
        except OSError as exc:
            # 档案已经写成了。笼统报一句「写入失败」会让人以为整件事都没成，
            # 于是去重跑一个其实已经完成的步骤，或者干脆以为档案也没写。
            print(f"错误：档案已写入 {archive}，但分享版没写成（{exc}）。"
                  f"档案可以照常用；再跑一次 compile 就能把分享版补上。",
                  file=sys.stderr)
            return 4
    except ReportContractError as exc:
        # 报告渲染不出来 = insights.json 里的值渲染不了，与 canonical_text 对不上
        # 是同一类问题，同样归 9。
        print(f"错误：{exc}", file=sys.stderr)
        return 9
    except ArchiveEmptyError as exc:
        # 8 而不是 0：什么都没写却返回成功，脚本会以为档案在那儿。
        print(f"错误：{exc}", file=sys.stderr)
        return 8
    except ArchiveContractError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 9
    except ArchiveOverwriteError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"错误：写入失败——{exc}", file=sys.stderr)
        return 4

    count = sum(len(items) for _, items in grouped)
    print(f"已写入 {archive}")
    print(f"  收录 {count} 条洞察，分 {len(grouped)} 节"
          f"（未勾选的、以及只进 Wrapped 的条目不在其中）")
    print(f"已写入 {share_path}")
    # 字段级 allowlist 拦不住**值**级泄露——关键词本身就来自正文，实测语料里
    # 出现过账号 handle 被抽成关键词。能拦住的只有人的眼睛，而人得先看得到它们。
    if keywords:
        print(f"  它包含这些关键词，发出去之前请自己过一遍（{len(keywords)} 个）：")
        print("    " + " · ".join(keywords))
    else:
        print("  它不含任何关键词。")
    return 0


def main(argv: list[str] | None = None) -> int:
    # 不用 argparse subparsers：现有用法 `kb-init <source>` 是位置参数，
    # 改成子命令解析会把它弄坏（下面有一条测试专盯这个）。
    argv = sys.argv[1:] if argv is None else argv
    # 只在「恰好两个参数、且第二个是已存在的文件」时才认作子命令。
    # 无条件按首参数分流会让一个真叫 validate 的目录再也无法作为 source 处理
    # ——那是拿一个合法输入名去换命令语法，代价方向反了。
    subcommands = {"validate": _validate_command, "compile": _compile_command}
    if (len(argv) == 2 and argv[0] in subcommands
            and Path(argv[1]).is_file()):
        return subcommands[argv[0]](argv[1])
    if (len(argv) == 2 and argv[0] in subcommands
            and not argv[1].startswith("-")          # `compile --help` 不是路径
            and not Path(argv[1]).exists()):
        # 形状与上面那条分支保持一致：两个参数、第二个像路径时，argv[0] 就是子命令。
        # 早先这里还多一个 `not Path(argv[0]).exists()`，于是当前目录里碰巧有个
        # 叫 compile 的东西时，这条分流会被跳过、落回「用法错误」并漏掉旧分享版
        # 提醒。那个条件是给**单参数**场景防「劫持一个真叫 compile 的目录」用的，
        # 在这里既拦不住什么，又制造了一个依赖 CWD 内容的行为差异。
        # 路径打错时报「用法错误」是在指错方向：用法明明是对的，错的是那个文件
        # 不在。用户会去检查命令怎么写，而不是去看路径——**报错码指错方向，
        # 人就会做错事**，这与 7 / 9 分开的理由是同一条。
        print(f"错误：找不到 {argv[1]}", file=sys.stderr)
        # 路径打错但目录对（最常见的那种手误）时，旧分享版照样躺在那儿。
        # 这个提醒只在那个文件真的存在时才会打印，所以不会误伤无关目录。
        _warn_if_stale_share_report(Path(argv[1]).parent)
        return 7
    if argv and argv[0] in subcommands and not Path(argv[0]).exists():
        print(f"用法：kb-init {argv[0]} <insights.md>", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0
    if args.source is None:
        parser.print_usage(sys.stderr)
        return 2

    from kb_init.extract import UnsafeArchiveError
    from kb_init.pipeline import run
    from kb_init.progress import ProgressPrinter

    # 退出码合同（见 README）：0 成功 / 1 输出冲突 / 2 用法错误
    # / 3 输入不安全或损坏 / 4 I-O 失败 / 5 产物已发布但索引未完成
    # / 6 索引完成但洞察层未生成 / 7 validate 判定 insights.md 不合法。
    # 默认不向普通用户吐 traceback。
    # 索引阶段冷启动要下载约 90MB 模型、按分钟计。在这之前用户看到的是一片空白，
    # 而一个盯着空白终端的人会以为它挂了然后 Ctrl-C——这个工具在他那里的
    # 唯一一次机会就没了（DESIGN R14）。
    progress = None if args.no_index else ProgressPrinter()
    try:
        counts = run(
            args.source,
            args.out,
            wikilinks=args.wikilinks,
            no_index=args.no_index,
            corpus_provenance=args.corpus_provenance.replace("-", "_"),
            progress=progress,
        )
    except FileExistsError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except UnsafeArchiveError as exc:
        print(f"错误：输入被安全检查拒绝——{exc}", file=sys.stderr)
        return 3
    except zipfile.BadZipFile as exc:
        print(f"错误：zip 文件损坏或不是 zip——{exc}", file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(f"错误：找不到输入路径——{exc}", file=sys.stderr)
        return 3
    except (ValueError, UnicodeError) as exc:
        print(f"错误：输入无法处理——{exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"错误：读写失败——{exc}", file=sys.stderr)
        return 4
    kept = counts["kept"]
    total = counts["total"]
    print(f"读入 {total} 篇，保留 {kept} 篇（留存 {kept / total:.0%}）" if total else "未找到 .md 文件")
    print(f"  空壳丢弃 {counts['dropped_stub']} 篇 / 重复丢弃 {counts['dropped_duplicate']} 篇")
    print(f"输出目录：{args.out}")
    # 索引失败不是整体失败：清洗产物已经发布，用户拿得到。用独立退出码让脚本
    # 能区分"什么都没有"和"东西在、只差索引"。
    if counts.get("index_status") == "failed":
        print(
            f"警告：清洗产物已写入，但索引未完成（{counts.get('index_reason')}）。"
            f"换一个 --out 目录重跑即可补上。",
            file=sys.stderr,
        )
        return 5
    # 6 与 5 的恢复动作不同：5 要重跑索引（需要网络与模型），6 只差洞察层。
    # 拓宽 5 的语义会让脚本在只需重算洞察时错误地重跑整个索引。
    if counts.get("insights_status") == "failed":
        print(
            f"警告：清洗产物与索引已写入，但洞察未生成"
            f"（{counts.get('insights_reason')}）。",
            file=sys.stderr,
        )
        return 6
    # 只有 failed 才报错。**skipped 不是失败**——`--no-index` 本来就没有洞察可渲染，
    # 给它报个错等于说「你用错了」，而那是一条一等公民的通道。
    if counts.get("report_status") == "failed":
        print(
            f"警告：清洗产物、索引与洞察都已写入，但报告未生成"
            f"（{counts.get('report_reason')}）。勾选清单 insights.md 照常可用。",
            file=sys.stderr,
        )
        return 10
    if counts.get("report_status") == "complete":
        print(f"报告：{Path(args.out) / 'report.private.html'}（双击打开看，再回到清单勾选）")
    return 0


def main_entry() -> None:
    sys.exit(main())
