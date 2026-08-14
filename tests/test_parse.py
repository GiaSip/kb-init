from pathlib import Path

from kb_init.parse import parse_file


def test_parses_frontmatter_and_body(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("---\ntitle: 我的笔记\ntags: [a, b]\n---\n\n正文内容\n", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.frontmatter["title"] == "我的笔记"
    assert doc.frontmatter["tags"] == ["a", "b"]
    assert doc.body.strip() == "正文内容"


def test_title_falls_back_to_h1_then_filename(tmp_path):
    with_h1 = tmp_path / "x.md"
    with_h1.write_text("# 标题在正文\n\n内容", encoding="utf-8")
    assert parse_file(with_h1, tmp_path).title == "标题在正文"

    bare = tmp_path / "只有文件名.md"
    bare.write_text("没有标题", encoding="utf-8")
    assert parse_file(bare, tmp_path).title == "只有文件名"


def test_malformed_frontmatter_does_not_crash(tmp_path):
    f = tmp_path / "bad.md"
    f.write_text("---\n: : : not yaml : :\n---\n正文", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.frontmatter == {}
    assert "正文" in doc.body


def test_utf8_bom_frontmatter_is_parsed(tmp_path):
    f = tmp_path / "bom.md"
    content = b"\xef\xbb\xbf" + "---\ntitle: BOM 笔记\n---\n\n正文\n".encode("utf-8")
    f.write_bytes(content)
    doc = parse_file(f, tmp_path)
    assert doc.frontmatter.get("title") == "BOM 笔记"
    assert doc.title == "BOM 笔记"


def test_frontmatter_title_wins_over_h1(tmp_path):
    f = tmp_path / "both.md"
    f.write_text("---\ntitle: frontmatter 标题\n---\n\n# H1 标题\n\n正文", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.title == "frontmatter 标题"


def test_relpath_and_ids_are_set(tmp_path):
    sub = tmp_path / "a"
    sub.mkdir()
    f = sub / "b.md"
    f.write_text("hi", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.source_relpath == "a/b.md"
    assert len(doc.doc_id) == 16
    assert len(doc.content_hash) == 16
    assert doc.date_source == "unresolved"


def test_oversized_frontmatter_is_skipped_not_parsed(tmp_path):
    """YAML 锚点炸弹防线：超大 frontmatter 块直接跳过解析。"""
    f = tmp_path / "bomb.md"
    huge = "a: " + "x" * (70 * 1024)
    f.write_text(f"---\n{huge}\n---\n\n正文内容", encoding="utf-8")
    doc = parse_file(f, tmp_path)
    assert doc.frontmatter == {}
    assert "正文内容" in doc.body
