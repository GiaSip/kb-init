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
