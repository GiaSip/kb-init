r"""源码卫生：docstring 里不许出现编码不了的字符。

Python 3.13 在编译期给 docstring 去缩进，那条路径会把它 encode 成 UTF-8——
于是一个含孤立代理项（`\ud800` 一类）的 docstring 在 **import 那一刻**就炸，
连一行测试都跑不到。3.12 完全看不出来。

这不是理论风险：`claude_md._encode` 的 docstring 里本来就写着这个字符
（它想**谈论**这个字符，结果**装进**了自己），首次 CI 上 3.13 的三个格子全红、
3.12 三个全绿——本机是 3.12，所以本地跑再多次也永远是绿的。

**只查 docstring，不查全部字面量**：实测普通字符串字面量在 3.12 / 3.13 上
都能正常 import（`X = "\ud800"` 两边都过）。把范围扩到所有字面量会顺手判死
`test_claude_md` 里那两个**故意**造的孤立代理项——它们是 `_encode` 的负例，
正是这个仓库需要保留的东西。检查器宁可窄而准。

⚠️ 本文件自己的 docstring 必须是 **raw string**，否则它会成为自己的第一个命中项。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SKIP = {".venv", "__pycache__", "dist", "build", ".git", ".pytest_cache"}

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef,
                     ast.AsyncFunctionDef)


def _python_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py")
                  if not SKIP & set(p.relative_to(root).parts))


def bad_docstrings(source: str) -> list[int]:
    """返回**行号**列表：这些 docstring 编码不了。空列表 = 干净。"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, _DOCSTRING_OWNERS):
            continue
        # clean=False：要查的是**源码里写的那一份**。clean=True 会先去缩进，
        # 而去缩进本身不改变有没有代理项，却让报出来的位置对不上源码。
        doc = ast.get_docstring(node, clean=False)
        if doc is None:
            continue
        try:
            doc.encode("utf-8")
        except UnicodeEncodeError:
            out.append(getattr(node, "lineno", 0))
    return out


def test_no_source_file_has_an_unencodable_docstring():
    files = _python_files(REPO)
    # 扫到 0 个文件时"没有命中"恒为真——那不叫干净，叫没查。
    # 这个下界刻意远低于现状（51 个），它防的是 rglob 因为改动而扫空，
    # 不是给现状背书。
    assert len(files) >= 20, f"只扫到 {len(files)} 个 .py，检查没真发生"

    offenders = {}
    for path in files:
        lines = bad_docstrings(path.read_text(encoding="utf-8"))
        if lines:
            offenders[str(path.relative_to(REPO))] = lines
    assert not offenders, (
        f"这些 docstring 含编码不了的字符，会让模块在 Python 3.13 上 import 即炸："
        f"{offenders}。把 docstring 改成 raw string（r\"\"\"…\"\"\"）即可——"
        f"它本来就只是想把这个字符**写出来**给人看。")


# ⚠️ 这两份样本里的 `\\ud800` 是**六个字符的转义序列**，不是一个孤立代理项。
# 真实的 .py 文件里也只能这么写——UTF-8 文件根本存不下一个裸的代理项，
# 而 `ast.parse` 收到一个真带代理项的 str 会在 `compile()` 那一步先炸掉，
# 于是负例根本走不到被检查的地方（第一版就是这么红的，红的原因还是错的）。
_POISONED = 'def f():\n    """doc \\ud800"""\n    return 1\n'
_LITERAL_ONLY = 'X = "\\ud800"\n\n\ndef f():\n    """干净的 docstring。"""\n'


def test_the_check_catches_a_real_offender():
    """负例：一个恒返回"干净"的检查器也能让上面那条全绿。"""
    assert bad_docstrings(_POISONED) == [1]


def test_the_check_leaves_ordinary_literals_alone():
    """普通字面量不是这条规则的目标——它们在 3.13 上 import 得动（已实测）。"""
    assert bad_docstrings(_LITERAL_ONLY) == []


@pytest.mark.parametrize("path", _python_files(REPO), ids=str)
def test_every_source_file_parses(path: pathlib.Path):
    """上面那条的前提：文件读不进来 / 语法错时不能静默算作"没有命中"。"""
    ast.parse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 文本读写必须显式给 encoding
#
# 不给的话用的是**平台默认编码**：POSIX 上是 UTF-8，Windows 上是 cp1252。
# 于是任何带非 ASCII 的读写在 Windows 上炸，而 macOS / Linux 上一路绿灯——
# 首次 CI 就是这样：六个格子里只有 Windows 那两个红，症状是
# `'charmap' codec can't decode byte 0x8f`。
#
# 产品代码当时是干净的，17 处全在测试里。但"测试里而已"不是理由：这些测试
# 正是 Windows 支持的**唯一证据**，它们在 Windows 上跑不动，README 里那行
# 「Windows x64 ✅」就没有东西撑着。
#
# **已知盲区，如实写明**：只查 `read_text` / `write_text` / 裸 `open()`。
# `Path.open()` 与 `zipfile.ZipFile.open()` 长得一样却是两回事（后者根本没有
# encoding 参数），要一起查就必须给 zipfile 开豁免——而豁免清单迟早会把真问题
# 也豁免掉。宁可窄而准：目前仓库里所有 `.open(` 都是二进制模式。
#
# `subprocess` 一起查：`text=True` 而不给 encoding，走的是同一个平台默认。
# 这一条抓到的是**产品**问题——`dates._from_git` 用 `text=True` 读 git 输出，
# Windows 上一条带非 ASCII 的 stderr 会在 `subprocess.run` 内部抛
# UnicodeDecodeError，而它既不是 OSError 也不是 SubprocessError，
# 那里的 `except` 接不住，整次运行随之崩掉。
_TEXT_IO = {"read_text", "write_text"}
_SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}


def _is_binary_mode(call: ast.Call) -> bool:
    mode = None
    if len(call.args) >= 2:
        mode = call.args[1]
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    return (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
            and "b" in mode.value)


def encodingless_io(source: str) -> list[int]:
    """返回**行号**列表：这些文本读写没写 encoding。空列表 = 干净。"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _TEXT_IO:
            out.append(node.lineno)
        elif (isinstance(func, ast.Name) and func.id == "open"
                and not _is_binary_mode(node)):
            out.append(node.lineno)
        elif (isinstance(func, ast.Attribute)
                and func.attr in _SUBPROCESS_FUNCS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
                and _wants_text(node)):
            out.append(node.lineno)
    return sorted(out)


def _wants_text(call: ast.Call) -> bool:
    """只有开了文本模式才需要 encoding——不开的话拿到的是 bytes，没有解码这一步。"""
    return any(kw.arg in ("text", "universal_newlines")
               and isinstance(kw.value, ast.Constant) and kw.value.value is True
               for kw in call.keywords)


def test_no_text_io_relies_on_the_platform_default_encoding():
    files = _python_files(REPO)
    assert len(files) >= 20, f"只扫到 {len(files)} 个 .py，检查没真发生"

    offenders = {}
    for path in files:
        lines = encodingless_io(path.read_text(encoding="utf-8"))
        if lines:
            offenders[str(path.relative_to(REPO))] = lines
    assert not offenders, (
        f"这些文本读写没给 encoding，会在 Windows（cp1252）上炸而本机全绿："
        f"{offenders}。补 `encoding=\"utf-8\"`。")


def test_the_encoding_check_catches_a_real_offender():
    """负例：恒返回"干净"的检查器也能让上面那条全绿。"""
    assert encodingless_io('p.write_text("x")\n') == [1]
    assert encodingless_io('open("f")\n') == [1]
    assert encodingless_io('subprocess.run(a, text=True)\n') == [1]


def test_the_encoding_check_leaves_binary_and_explicit_calls_alone():
    """正当写法不能被判死，否则这条规则会逼着后来的人给它开豁免。"""
    assert encodingless_io('open("f", "wb")\n') == []
    assert encodingless_io('open("f", mode="rb")\n') == []
    assert encodingless_io('p.write_text("x", encoding="utf-8")\n') == []
    # 不开文本模式就没有解码这一步，拿到的是 bytes。
    assert encodingless_io('subprocess.run(a, capture_output=True)\n') == []
    assert encodingless_io(
        'subprocess.run(a, text=True, encoding="utf-8")\n') == []
