import argparse
import sys

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
    return 0


def main_entry() -> None:
    sys.exit(main())
