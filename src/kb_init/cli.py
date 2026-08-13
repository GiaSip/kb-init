import argparse
import sys
import zipfile

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
    parser.add_argument("source", nargs="?", help="导出文件夹或 zip 路径")
    parser.add_argument("-o", "--out", default="kb-out", help="输出目录（默认 kb-out）")
    return parser


def main(argv: list[str] | None = None) -> int:
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

    # 退出码合同（见 README）：0 成功 / 1 输出冲突 / 2 用法错误
    # / 3 输入不安全或损坏 / 4 I-O 失败。默认不向普通用户吐 traceback。
    try:
        counts = run(args.source, args.out, wikilinks=args.wikilinks)
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
    return 0


def main_entry() -> None:
    sys.exit(main())
