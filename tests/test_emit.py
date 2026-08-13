# tests/test_emit.py
import pytest

from kb_init.emit import emit
from kb_init.model import Document


def _doc(doc_id: str, title: str, status: str = "kept") -> Document:
    return Document(
        doc_id=doc_id.ljust(16, "0"),
        source_relpath=f"deep/nested/{doc_id}.md",
        content_hash="c" * 16,
        title=title,
        body="正文" * 200,
        frontmatter={},
        created="2024-01-01",
        date_source="frontmatter",
        status=status,
    )


def test_only_kept_docs_are_written(tmp_path):
    docs = emit([_doc("a", "保留"), _doc("b", "丢弃", status="dropped")], tmp_path)
    written = list((tmp_path / "knowledge").glob("*.md"))
    assert len(written) == 1
    assert docs[0].out_relpath is not None
    assert docs[1].out_relpath is None


def test_out_relpath_is_frozen_and_file_exists(tmp_path):
    docs = emit([_doc("a", "标题")], tmp_path)
    target = tmp_path / docs[0].out_relpath
    assert target.exists()
    assert docs[0].out_relpath.startswith("knowledge/")


def test_paths_are_flattened_not_nested(tmp_path):
    """Notion 导出深达 11-15 层，必须拍平。"""
    docs = emit([_doc("a", "标题")], tmp_path)
    assert docs[0].out_relpath.count("/") == 1


def test_title_collision_gets_unique_path(tmp_path):
    docs = emit([_doc("a", "同名"), _doc("b", "同名")], tmp_path)
    assert docs[0].out_relpath != docs[1].out_relpath


def test_refuses_to_overwrite_existing_output(tmp_path):
    (tmp_path / "knowledge").mkdir(parents=True)
    (tmp_path / "knowledge" / "x.md").write_text("已有内容")
    with pytest.raises(FileExistsError):
        emit([_doc("a", "标题")], tmp_path)


def test_default_uses_standard_markdown_links(tmp_path):
    doc = _doc("a", "标题")
    doc.body = "见 [[另一篇]] 的说明"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[另一篇]]" not in written
    assert "[另一篇](另一篇.md)" in written


def test_wikilinks_flag_preserves_dialect(tmp_path):
    doc = _doc("a", "标题")
    doc.body = "见 [[另一篇]] 的说明"
    emit([doc], tmp_path, wikilinks=True)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[另一篇]]" in written


def test_frontmatter_carries_doc_id(tmp_path):
    docs = emit([_doc("a", "标题")], tmp_path)
    written = (tmp_path / docs[0].out_relpath).read_text(encoding="utf-8")
    assert docs[0].doc_id in written


def test_anchor_wikilink_converts_to_standard_markdown(tmp_path):
    """[[目标#小节]] → [目标#小节](目标.md#小节)"""
    doc = _doc("a", "标题")
    doc.body = "见 [[目标#小节]] 的说明"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[目标#小节]]" not in written
    assert "[目标#小节](目标.md#小节)" in written


def test_alias_plus_anchor_wikilink_converts_correctly(tmp_path):
    """[[目标#小节|显示文字]] → [显示文字](目标.md#小节)"""
    doc = _doc("a", "标题")
    doc.body = "见 [[目标#小节|显示文字]] 的说明"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[目标#小节|显示文字]]" not in written
    assert "[显示文字](目标.md#小节)" in written


def test_three_same_title_docs_get_unique_paths_and_content(tmp_path):
    """三篇以上同名文档，路径互不相同且磁盘内容各自正确。"""
    doc_a = _doc("aaa", "同名")
    doc_b = _doc("bbb", "同名")
    doc_c = _doc("ccc", "同名")
    docs = emit([doc_a, doc_b, doc_c], tmp_path)
    paths = [d.out_relpath for d in docs]
    assert len(set(paths)) == 3  # 三个路径互不相同
    for doc in docs:
        content = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
        assert doc.doc_id in content  # 每个文件包含自己的 doc_id


def test_wikilinks_in_fenced_code_block_are_not_converted(tmp_path):
    doc = _doc("a", "标题")
    doc.body = "普通 [[链接]] 文字\n```\n代码里的 [[不转换]]\n```\n后续 [[也转换]]"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[链接]]" not in written      # 普通文本的 wikilink 被转换
    assert "[[不转换]]" in written        # 代码块内的 wikilink 保留
    assert "[[也转换]]" not in written    # 代码块后的普通文本也被转换


def test_wikilinks_in_inline_code_are_not_converted(tmp_path):
    doc = _doc("a", "标题")
    doc.body = "普通 [[链接]] 和 `代码里的 [[不转换]]` 后续"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[链接]]" not in written
    assert "[[不转换]]" in written


def test_same_file_anchor_wikilink_converts_correctly(tmp_path):
    """[[#小节]] → [#小节](#小节)（同文件锚点，标准 Markdown 合法）"""
    doc = _doc("a", "标题")
    doc.body = "见 [[#小节]] 的说明"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[#小节]]" not in written
    assert "[#小节](#小节)" in written
    assert ".md#" not in written  # 不能产生空文件名 .md#小节


def test_same_file_anchor_with_alias_converts_correctly(tmp_path):
    """[[#小节|显示]] → [显示](#小节)"""
    doc = _doc("a", "标题")
    doc.body = "见 [[#小节|显示]] 的说明"
    emit([doc], tmp_path)
    written = (tmp_path / doc.out_relpath).read_text(encoding="utf-8")
    assert "[[#小节|显示]]" not in written
    assert "[显示](#小节)" in written
