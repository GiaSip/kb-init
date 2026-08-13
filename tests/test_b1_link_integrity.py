# tests/test_b1_link_integrity.py
"""B1 验收测试：所有输出文件的正文 Markdown 链接必须指向真实存在的目标文件。

这是 B1 的核心回归测试——之前的 E2E 只验了 manifest 的 out_relpath，
从没验过正文链接指向的文件是否存在。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from kb_init.pipeline import run

# 匹配标准 Markdown 链接中的目标部分: [label](target)
_MD_LINK = re.compile(r"\[(?:[^\]]*)\]\(([^)]+)\)")


def _extract_md_targets(text: str) -> list[str]:
    """从正文中提取所有 Markdown 链接目标（去掉锚点）。"""
    targets = []
    for m in _MD_LINK.finditer(text):
        target = m.group(1)
        # 去掉锚点部分
        if "#" in target:
            target = target.split("#", 1)[0]
        if target:
            targets.append(target)
    return targets


def _build_corpus(root: Path) -> None:
    """构造覆盖 B1 五种失败场景的语料。

    场景 1: [[Project A]] 被写成 (Project A.md) 而实际 slug 是 Project-A.md
    场景 2: 同名第二篇落成 同名-1.md，但所有 [[同名]] 仍指向第一篇
    场景 3: 原有 source_relpath 格式的相对链接在目录拍平后无重映射
    场景 4: 链接目标被判 stub/duplicate 后没有输出文件
    场景 5: [[foo.md]] 带后缀会被变成 foo.md.md
    """
    long_body = "内容" * 110  # 220 chars > 200 min_body_chars

    # 被链接到的目标：标题含空格，slug 会变成 Project-A.md
    (root / "project_a.md").write_text(
        f"# Project A\n\n{long_body}", encoding="utf-8"
    )

    # 同名第一篇（先处理，被 mark kept）
    (root / "duplicate_title_1.md").write_text(
        f"# 同名文档\n\n{long_body}", encoding="utf-8"
    )
    # 同名第二篇（后处理，同名所以 slug 会加 -1 后缀）
    (root / "duplicate_title_2.md").write_text(
        f"# 同名文档\n\n{long_body}另外内容", encoding="utf-8"
    )

    # 会被判 stub（正文 < 200 字符）的文档
    (root / "stub_target.md").write_text(
        "# Stub文档\n\n短", encoding="utf-8"
    )

    # 引用文档：包含各种链接形态
    (root / "linker.md").write_text(
        f"# 引用文档\n\n"
        # 场景 1: 标题含空格，slug 后变 Project-A.md
        "链接1: [[Project A]]\n\n"
        # 场景 2: 同名第二篇
        "链接2: [[同名文档]]\n\n"
        # 场景 4: 目标会被判 stub
        "链接4: [[Stub文档]]\n\n"
        # 场景 5: 自带 .md 后缀的 wikilink
        "链接5: [[project_a.md]]\n\n"
        f"{long_body}",
        encoding="utf-8",
    )


def test_b1_all_output_links_resolve_to_existing_files(tmp_path):
    """核心验收：扫描所有 knowledge/*.md，断言每个 .md 链接目标文件都真实存在。

    如果此测试在重构前是红的，说明 B1 缺陷确实存在。
    """
    src = tmp_path / "src"
    src.mkdir()
    _build_corpus(src)

    out = tmp_path / "out"
    run(src, out, run_id="b1-test")

    knowledge = out / "knowledge"
    md_files = list(knowledge.glob("*.md"))
    assert md_files, "knowledge/ 目录为空，测试无效"

    dead_links: list[tuple[str, str]] = []  # (源文件, 死链目标)

    for md_file in sorted(md_files):
        # 跳过 frontmatter（--- 块），只扫描正文
        text = md_file.read_text(encoding="utf-8")
        lines = text.split("\n")
        in_frontmatter = False
        body_lines = []
        fm_count = 0
        for line in lines:
            if line.strip() == "---":
                fm_count += 1
                if fm_count <= 2:
                    in_frontmatter = fm_count == 1
                    continue
            if not in_frontmatter:
                body_lines.append(line)
        body = "\n".join(body_lines)

        for target in _extract_md_targets(body):
            if not target.endswith(".md"):
                continue
            target_path = knowledge / target
            if not target_path.exists():
                dead_links.append((md_file.name, target))

    assert not dead_links, (
        f"发现 {len(dead_links)} 条死链（B1 缺陷证据）:\n"
        + "\n".join(f"  {src} → {tgt}" for src, tgt in dead_links)
    )


# ── 五个单场景回归测试（重构后应全部通过）────────────────────────────────────

def test_b1_scenario1_space_in_title_slug(tmp_path):
    """场景 1: [[Project A]] 链接应指向实际 slug 文件 Project-A.md，而非 Project A.md"""
    src = tmp_path / "src"
    src.mkdir()
    long_body = "内容" * 110
    (src / "project_a.md").write_text(f"# Project A\n\n{long_body}", encoding="utf-8")
    (src / "linker.md").write_text(
        f"# 引用者\n\n[[Project A]]\n\n{long_body}", encoding="utf-8"
    )
    out = tmp_path / "out"
    run(src, out, run_id="s1")
    knowledge = out / "knowledge"
    linker_files = [f for f in knowledge.glob("*.md") if "引用者" in f.stem or "linker" in f.stem.lower()]
    # 找到引用者文件（可能是任何名字，通过 doc_id 追踪）
    for md_file in knowledge.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        if "[[Project A]]" not in text and "Project A" in text and "Project-A" in text:
            # 找到了引用文件
            for target in _extract_md_targets(text):
                if target.endswith(".md"):
                    assert (knowledge / target).exists(), (
                        f"死链: {md_file.name} → {target}"
                    )


def test_b1_scenario2_same_title_second_doc(tmp_path):
    """场景 2: 同名第二篇落成 同名-1.md，[[同名文档]] 应正确解析"""
    src = tmp_path / "src"
    src.mkdir()
    long_body = "内容" * 110
    (src / "doc1.md").write_text(f"# 同名\n\n{long_body}", encoding="utf-8")
    (src / "doc2.md").write_text(f"# 同名\n\n{long_body}额外", encoding="utf-8")
    (src / "linker.md").write_text(
        f"# 引用者\n\n[[同名]]\n\n{long_body}", encoding="utf-8"
    )
    out = tmp_path / "out"
    run(src, out, run_id="s2")
    knowledge = out / "knowledge"
    # 所有输出文件的链接均不得有死链
    dead = []
    for md_file in knowledge.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        for target in _extract_md_targets(text):
            if target.endswith(".md") and not (knowledge / target).exists():
                dead.append((md_file.name, target))
    assert not dead, f"场景2死链: {dead}"


def test_b1_scenario3_flat_path_remap(tmp_path):
    """场景 3: 目录内的 .md 文件，链接在拍平后仍可解析"""
    src = tmp_path / "src"
    src.mkdir()
    long_body = "内容" * 110
    nested = src / "sub" / "dir"
    nested.mkdir(parents=True)
    (nested / "target.md").write_text(f"# 目标文档\n\n{long_body}", encoding="utf-8")
    (src / "linker.md").write_text(
        f"# 引用者\n\n[[目标文档]]\n\n{long_body}", encoding="utf-8"
    )
    out = tmp_path / "out"
    run(src, out, run_id="s3")
    knowledge = out / "knowledge"
    dead = []
    for md_file in knowledge.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        for target in _extract_md_targets(text):
            if target.endswith(".md") and not (knowledge / target).exists():
                dead.append((md_file.name, target))
    assert not dead, f"场景3死链: {dead}"


def test_b1_scenario4_stub_target_no_dead_link(tmp_path):
    """场景 4: 链接目标被判 stub，正文中不应产生死链（应标记为 unresolved 纯文本）"""
    src = tmp_path / "src"
    src.mkdir()
    long_body = "内容" * 110
    (src / "stub.md").write_text("# 短篇\n\n短", encoding="utf-8")
    (src / "linker.md").write_text(
        f"# 引用者\n\n[[短篇]]\n\n{long_body}", encoding="utf-8"
    )
    out = tmp_path / "out"
    run(src, out, run_id="s4")
    knowledge = out / "knowledge"
    dead = []
    for md_file in knowledge.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        for target in _extract_md_targets(text):
            if target.endswith(".md") and not (knowledge / target).exists():
                dead.append((md_file.name, target))
    assert not dead, f"场景4死链: {dead}"


def test_b1_scenario5_explicit_md_suffix_no_double_extension(tmp_path):
    """场景 5: [[foo.md]] 不应产生 foo.md.md"""
    src = tmp_path / "src"
    src.mkdir()
    long_body = "内容" * 110
    (src / "target.md").write_text(f"# Target\n\n{long_body}", encoding="utf-8")
    (src / "linker.md").write_text(
        f"# 引用者\n\n[[target.md]]\n\n{long_body}", encoding="utf-8"
    )
    out = tmp_path / "out"
    run(src, out, run_id="s5")
    knowledge = out / "knowledge"
    # 不得出现 .md.md 结尾的文件
    double_ext = list(knowledge.glob("*.md.md"))
    assert not double_ext, f"出现了双重扩展名文件: {double_ext}"
    # 且所有 .md 链接目标存在
    dead = []
    for md_file in knowledge.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        for target in _extract_md_targets(text):
            if target.endswith(".md") and not (knowledge / target).exists():
                dead.append((md_file.name, target))
    assert not dead, f"场景5死链: {dead}"


def test_ambiguous_alias_does_not_produce_live_wrong_link(tmp_path):
    """歧义别名必须降级为 unresolved，绝不能指向错误的那一篇。

    错链比死链严重：manifest 会显示解析成功，没人会去查。
    """
    src = tmp_path / "src"
    src.mkdir()
    long_body = "内容" * 110
    # 两篇文档的 stem 相同（不同目录），构成歧义别名
    (src / "a").mkdir()
    (src / "b").mkdir()
    (src / "a" / "note.md").write_text(f"# 甲\n\n{long_body}", encoding="utf-8")
    (src / "b" / "note.md").write_text(f"# 乙\n\n{long_body}别的", encoding="utf-8")
    (src / "linker.md").write_text(
        f"# 引用者\n\n见 [[note]] 的说明\n\n{long_body}", encoding="utf-8"
    )
    out = tmp_path / "out"
    run(src, out, run_id="ambig")

    knowledge = out / "knowledge"
    # 两篇同 stem 不同目录的文档都必须保留（不得被误判成文件系统碰撞）
    assert len(list(knowledge.glob("*.md"))) == 3, "不同目录的同名文档被误删了"

    linker = next(f for f in knowledge.glob("*.md") if "引用者" in f.stem)
    body = linker.read_text(encoding="utf-8")

    # 只断言"没有死链"是不够的——指向甲或乙都会通过。必须断言它
    # 既没有变成链接、也确实进了 unresolved 账。
    assert "](甲.md)" not in body, "歧义别名指向了甲——这是活着的错链"
    assert "](乙.md)" not in body, "歧义别名指向了乙——这是活着的错链"
    assert "note" in body, "降级后的纯文本应保留原标签"

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    targets = [u["target"] for u in manifest["unresolved_links"]]
    assert "note" in targets, f"歧义链接未记入 unresolved_links：{targets}"


def test_wikilinks_flag_still_remaps_standard_links(tmp_path):
    """--wikilinks 只保留 [[...]] 方言，不得跳过标准链接的重映射。"""
    src = tmp_path / "src"
    src.mkdir()
    long_body = "内容" * 110
    (src / "target page.md").write_text(
        f"# Target Page\n\n{long_body}", encoding="utf-8"
    )
    (src / "linker.md").write_text(
        f"# 引用者\n\n见 [标题](target%20page.md) 的说明\n\n{long_body}",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    run(src, out, wikilinks=True, run_id="wl")

    knowledge = out / "knowledge"
    linker = next(f for f in knowledge.glob("*.md") if "引用者" in f.stem)
    body = linker.read_text(encoding="utf-8")

    # 只遍历"剩余链接"是不够的——若链接被降级成纯文本，循环为空也会通过。
    # 必须断言链接确实存在、且指向了改写后的真实文件。
    targets = [t for t in _extract_md_targets(body) if t.endswith(".md")]
    assert targets, "标准链接被降级成纯文本了，--wikilinks 不该跳过重映射"
    assert "target%20page.md" not in body, "原始 URL 编码路径没有被重映射"
    for target in targets:
        assert (knowledge / target).exists(), f"{linker.name} → {target}"
