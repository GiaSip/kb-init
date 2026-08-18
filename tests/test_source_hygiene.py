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
