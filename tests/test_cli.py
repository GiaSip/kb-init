import pytest
from kb_init.cli import main


def test_version_flag_prints_version(capsys):
    rc = main(["--version"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() != ""


def test_no_args_returns_usage_error():
    assert main([]) == 2


def test_missing_source_path_gives_clean_error(tmp_path, capsys):
    """不存在的输入路径必须给退出码 3 + 单行诊断，不吐 traceback。"""
    rc = main([str(tmp_path / "不存在"), "-o", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 3
    assert "Traceback" not in err
    assert "错误：" in err


def test_corrupt_zip_gives_clean_error(tmp_path, capsys):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip at all")
    rc = main([str(bad), "-o", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 3
    assert "Traceback" not in err


def _fake_summary(**over):
    base = {"total": 10, "kept": 6, "dropped_stub": 4, "dropped_duplicate": 0,
            "index_status": "complete", "index_reason": None,
            "insights_status": "complete", "insights_reason": None}
    base.update(over)
    return base


def test_exit_code_6_when_only_insights_failed(tmp_path, monkeypatch, capsys):
    from kb_init.cli import main

    monkeypatch.setattr("kb_init.pipeline.run",
                        lambda *a, **k: _fake_summary(insights_status="failed",
                                                      insights_reason="naming_failed"))
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 6
    assert "洞察" in capsys.readouterr().err


def test_exit_code_5_still_wins_when_index_failed(tmp_path, monkeypatch):
    from kb_init.cli import main

    monkeypatch.setattr("kb_init.pipeline.run",
                        lambda *a, **k: _fake_summary(
                            index_status="failed", index_reason="model_unavailable",
                            insights_status="skipped", insights_reason="index_failed"))
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 5


def test_exit_code_0_when_everything_completes(tmp_path, monkeypatch):
    from kb_init.cli import main

    monkeypatch.setattr("kb_init.pipeline.run", lambda *a, **k: _fake_summary())
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 0


# ---------------- kb-init validate ----------------

def _write_pair(tmp_path, insights_status="complete"):
    import json

    from kb_init.insights_md import render_markdown

    payload = {
        "schema_version": "0.1", "run_id": "r1", "corpus_hash": "c1",
        "counts": {"topic": 1, "residual": 0, "corpus": 0, "total": 1},
        "presentation": {"group_refs": [],
                         "truncated": {"shown": 1, "total": 1,
                                       "omitted_group_refs": [], "omitted_docs": 0}},
        "insights": [{"insight_id": "T1", "family": "topic",
                      "kind": "topic_cluster", "canonical_text": "文本",
                      "payload": {}, "evidence": {"doc_ids": [], "stat": None},
                      "claude_md": None}],
    }
    (tmp_path / "insights.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "insights.md").write_text(render_markdown(payload), encoding="utf-8")
    if insights_status is not None:
        (tmp_path / "manifest.json").write_text(
            json.dumps({"insights_status": insights_status, "insights_reason": None}),
            encoding="utf-8")
    return payload


def test_validate_accepts_a_matching_pair(tmp_path, capsys):
    from kb_init.cli import main

    _write_pair(tmp_path)
    assert main(["validate", str(tmp_path / "insights.md")]) == 0
    assert "1 条" in capsys.readouterr().out


def test_validate_rejects_unknown_id_with_line_number(tmp_path, capsys):
    from kb_init.cli import main

    _write_pair(tmp_path)
    path = tmp_path / "insights.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n- [x] `T9` 冒出来的\n",
                    encoding="utf-8")
    assert main(["validate", str(path)]) == 7
    err = capsys.readouterr().err
    assert "T9" in err and "行" in err


def test_validate_reports_missing_json_clearly(tmp_path, capsys):
    from kb_init.cli import main

    _write_pair(tmp_path)
    (tmp_path / "insights.json").unlink()
    assert main(["validate", str(tmp_path / "insights.md")]) == 7
    assert "insights.json" in capsys.readouterr().err


def test_validate_requires_exactly_one_path(tmp_path):
    from kb_init.cli import main

    assert main(["validate"]) == 2


def test_normal_run_still_works_after_adding_the_subcommand(tmp_path):
    """加子命令最容易踩的坑：把原来的 `kb-init <source>` 用法弄坏。"""
    from kb_init.cli import main

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("# a\n\n" + "内容内容内容 " * 60, encoding="utf-8")
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-index"]) == 0


def test_a_directory_literally_named_validate_is_still_processable(tmp_path, monkeypatch):
    """无条件按首参数分流会吃掉一个合法的 source 名。"""
    from kb_init.cli import main

    monkeypatch.chdir(tmp_path)
    src = tmp_path / "validate"
    src.mkdir()
    (src / "a.md").write_text("# a\n\n" + "内容内容内容 " * 60, encoding="utf-8")
    assert main(["validate", "-o", str(tmp_path / "out"), "--no-index"]) == 0
    assert (tmp_path / "out" / "knowledge").is_dir()


def test_corpus_provenance_flag_reaches_the_gate(tmp_path):
    """provenance 只换了默认值、调用方从不传的话，条件③永远 not_evaluable，
    那个机制就只是摆设。"""
    import json

    from kb_init.cli import main

    src = tmp_path / "src"
    src.mkdir()
    for i in range(14):
        (src / f"d{i:02d}.md").write_text(
            f"# 标题{i}\n\nblob:alpha\n" + ("内容内容内容内容 " * 40), encoding="utf-8")
    out = tmp_path / "out"
    import kb_init.pipeline as pl
    from tests.fakes import BlobEmbedder

    real_run = pl.run
    pl.run = lambda *a, **k: real_run(*a, **{**k, "embedder": BlobEmbedder()})
    try:
        assert main([str(src), "-o", str(out), "--corpus-provenance", "third-party"]) == 0
    finally:
        pl.run = real_run
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    gate = payload["revisit_gate"]
    assert gate["inputs"]["corpus_provenance"] == "third_party"
    states = {c["id"]: c["state"] for c in gate["conditions"]}
    assert states["residual_high"] != "not_evaluable"


def test_validate_refuses_when_manifest_says_insights_failed(tmp_path, capsys):
    import json

    from kb_init.cli import main

    _write_pair(tmp_path, insights_status="failed")
    assert main(["validate", str(tmp_path / "insights.md")]) == 7
    assert "complete" in capsys.readouterr().err


def test_validate_accepts_when_manifest_says_complete(tmp_path):
    import json

    from kb_init.cli import main

    _write_pair(tmp_path)
    assert main(["validate", str(tmp_path / "insights.md")]) == 0


def test_validate_refuses_when_manifest_is_missing(tmp_path, capsys):
    """「读不到就跳过」是兜底路径的经典形态——read_index 那边已经拒读，
    这里放行就是两个入口两套标准。"""
    from kb_init.cli import main

    _write_pair(tmp_path, insights_status=None)
    assert main(["validate", str(tmp_path / "insights.md")]) == 7
    assert "insights_status" in capsys.readouterr().err


def test_validate_refuses_when_manifest_is_corrupt(tmp_path):
    from kb_init.cli import main

    _write_pair(tmp_path, insights_status=None)
    (tmp_path / "manifest.json").write_text("{ 这不是 json", encoding="utf-8")
    assert main(["validate", str(tmp_path / "insights.md")]) == 7


def test_validate_refuses_when_the_status_field_is_absent(tmp_path):
    import json

    from kb_init.cli import main

    _write_pair(tmp_path, insights_status=None)
    (tmp_path / "manifest.json").write_text(json.dumps({"run_id": "r1"}),
                                            encoding="utf-8")
    assert main(["validate", str(tmp_path / "insights.md")]) == 7


def test_validate_refuses_when_manifest_top_level_is_not_an_object(tmp_path):
    """合法 JSON 但顶层是数组/null/字符串时，下标会抛 TypeError——
    read_index 那边已经捕了，这里不能漏，否则同一种输入两个入口两种行为。"""
    from kb_init.cli import main

    for payload in ("[]", "null", '"just a string"'):
        _write_pair(tmp_path, insights_status=None)
        (tmp_path / "manifest.json").write_text(payload, encoding="utf-8")
        assert main(["validate", str(tmp_path / "insights.md")]) == 7, payload


# ---------------- kb-init compile ----------------

def _bundle_insight(iid, family, kind, payload, claude_md):
    from kb_init.insights import Insight, render

    return {"insight_id": iid, "family": family, "kind": kind,
            "payload": payload,
            "canonical_text": render(Insight(iid, family, kind, payload, "")),
            "evidence": {"doc_ids": [], "stat": None},
            "claude_md": claude_md}


def _write_bundle(tmp_path, *, insights=None, manifest_over=None, schema="0.1"):
    """比 _write_pair 多两样：knowledge/ 目录，以及 manifest 里的身份字段。"""
    import json

    from kb_init.insights_md import render_markdown

    if insights is None:
        # canonical_text 由**真渲染器**生成，不手写：手写一份就等于给它开了
        # 第二个生成器，而 compile 会（正确地）把两者不等判为 9。
        insights = [
            _bundle_insight(
                "T1", "topic", "topic_cluster",
                {"doc_count": 9, "keywords": ["甲", "乙"], "share_of_kept": 0.03,
                 "evidence_titles": ["标题一", "标题二"]},
                {"section": "focus_areas"}),
            _bundle_insight(
                "C1", "corpus", "retention",
                {"total": 100, "kept": 40, "dropped_stub": 60,
                 "dropped_duplicate": 0},
                None),
        ]
    payload = {
        "schema_version": schema, "run_id": "r1", "corpus_hash": "c1",
        "counts": {"topic": 1, "residual": 0, "corpus": 1, "total": 2},
        "presentation": {"group_refs": [],
                         "truncated": {"shown": 1, "total": 1,
                                       "omitted_group_refs": [], "omitted_docs": 0}},
        "insights": insights,
    }
    (tmp_path / "knowledge").mkdir(exist_ok=True)
    (tmp_path / "insights.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "insights.md").write_text(render_markdown(payload), encoding="utf-8")
    man = {"insights_status": "complete", "insights_reason": None,
           "run_id": "r1", "corpus_hash": "c1"}
    man.update(manifest_over or {})
    (tmp_path / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return payload


def _uncheck(tmp_path, *ids):
    path = tmp_path / "insights.md"
    text = path.read_text(encoding="utf-8")
    for i in ids:
        text = text.replace(f"- [x] `{i}`", f"- [ ] `{i}`")
    path.write_text(text, encoding="utf-8")


def _archive(tmp_path):
    return tmp_path / "knowledge" / "CLAUDE.md"


def test_compile_happy_path_writes_archive(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    out = _archive(tmp_path).read_text(encoding="utf-8")
    assert "## 关注领域" in out
    assert "- 这 9 篇里最具区分度的词是 甲 · 乙 — 占 kept 3.0%" in out
    assert "读入 100 篇" not in out, "corpus 族勾着也不该进档案"
    assert (tmp_path / "compile.json").exists()


@pytest.mark.parametrize("bad", [
    None,                                    # manifest 缺失
    "{不是 json",                             # 损坏
    '{"other": 1}',                          # 没有 insights_status
    '[]',                                    # 顶层不是对象
])
def test_compile_manifest_gate_four_states(tmp_path, bad):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    path = tmp_path / "manifest.json"
    if bad is None:
        path.unlink()
    else:
        path.write_text(bad, encoding="utf-8")
    assert main(["compile", str(tmp_path / "insights.md")]) == 7
    assert not _archive(tmp_path).exists()


@pytest.mark.parametrize("field", ["run_id", "corpus_hash"])
def test_compile_identity_mismatch_with_manifest(tmp_path, field):
    """manifest 与 json 不是同一次运行的产物 → 9（Codex 审 #2）。"""
    from kb_init.cli import main

    _write_bundle(tmp_path, manifest_over={field: "别的"})
    assert main(["compile", str(tmp_path / "insights.md")]) == 9
    assert not _archive(tmp_path).exists()


def test_compile_schema_version_mismatch(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path, schema="0.9")
    assert main(["compile", str(tmp_path / "insights.md")]) == 9


def test_stale_json_reports_9_not_7(tmp_path):
    """顺序纪律的守卫（Codex 审 #4）：旧 json 配一份与之匹配的 md。

    md 与 json 完全对得上，validate_markdown 一定过；若版本 gate 排在它后面，
    这里会先撞上别的错误码。真正的原因是 json 太旧，修复动作在工具手上。
    """
    from kb_init.cli import main

    _write_bundle(tmp_path, schema="0.0.1")
    assert main(["validate", str(tmp_path / "insights.md")]) == 0, (
        "前提：这份 md 与 json 是匹配的，7 无从谈起")
    assert main(["compile", str(tmp_path / "insights.md")]) == 9


def test_compile_unknown_section_unchecked_reports_9_not_8(tmp_path):
    """§5.1 的守卫：唯一可归档条目是未知 section 且**未勾选**。

    若结构 gate 晚于按勾选过滤，这里会走到「没有可归档条目」而报 8，
    把「工具不认识这一节」说成「你一条都没勾」。
    """
    from kb_init.cli import main

    _write_bundle(tmp_path, insights=[
        {"insight_id": "T1", "family": "topic", "kind": "topic_cluster",
         "canonical_text": "未来的一条", "payload": {},
         "evidence": {"doc_ids": [], "stat": None},
         "claude_md": {"section": "blind_spots"}}])
    _uncheck(tmp_path, "T1")
    assert main(["compile", str(tmp_path / "insights.md")]) == 9
    assert not _archive(tmp_path).exists()


def test_compile_zero_archivable_writes_nothing(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    _uncheck(tmp_path, "T1")
    assert main(["compile", str(tmp_path / "insights.md")]) == 8
    assert not _archive(tmp_path).exists()


def test_compile_refuses_overwrite(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    _archive(tmp_path).write_text("我自己的一篇笔记", encoding="utf-8")
    assert main(["compile", str(tmp_path / "insights.md")]) == 1
    assert _archive(tmp_path).read_text(encoding="utf-8") == "我自己的一篇笔记"


def test_compile_rerun_is_idempotent(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    assert main(["compile", str(tmp_path / "insights.md")]) == 0


def test_compile_missing_knowledge_dir(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    (tmp_path / "knowledge").rmdir()
    assert main(["compile", str(tmp_path / "insights.md")]) == 4
    assert not (tmp_path / "knowledge").exists()


def test_compile_tampered_canonical_text_reports_9(tmp_path):
    import json

    from kb_init.cli import main

    payload = _write_bundle(tmp_path)
    payload["insights"][0]["canonical_text"] = "我自己改的文案"
    (tmp_path / "insights.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert main(["compile", str(tmp_path / "insights.md")]) == 9


def test_compile_usage_error_without_file(tmp_path):
    from kb_init.cli import main

    assert main(["compile"]) == 2


def test_source_dir_named_compile_still_works(tmp_path, monkeypatch):
    """一个真叫 compile 的目录仍按 source 处理——新子命令不许弄坏位置参数用法。"""
    from kb_init.cli import main

    src = tmp_path / "compile"
    src.mkdir()
    monkeypatch.setattr("kb_init.pipeline.run", lambda *a, **k: _fake_summary())
    assert main([str(src), "-o", str(tmp_path / "out")]) == 0


def test_missing_knowledge_dir_reports_4_even_when_nothing_checked(tmp_path):
    """顺序守卫：目录被删 + 一条都没勾。

    若 knowledge/ 的检查拖到最后才做，这里会先撞上「你一条都没勾」（8），
    把「目录不见了」说成「你没勾选」——诊断指向完全错误的方向。
    """
    from kb_init.cli import main

    _write_bundle(tmp_path)
    _uncheck(tmp_path, "T1")
    (tmp_path / "knowledge").rmdir()
    assert main(["compile", str(tmp_path / "insights.md")]) == 4


def test_knowledge_symlink_reports_4(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "knowledge").rmdir()
    (tmp_path / "knowledge").symlink_to(elsewhere, target_is_directory=True)
    assert main(["compile", str(tmp_path / "insights.md")]) == 4
    assert not (elsewhere / "CLAUDE.md").exists()


def test_missing_knowledge_dir_reports_4_even_when_manifest_is_broken(tmp_path):
    """目录不见了 + manifest 也坏了：报 4 而不是 7。

    「这个目录根本不是一个 kb-init 输出目录」是最结构性的那个事实，
    它必须先说；否则用户会去修 manifest，修完才发现目录也没了。
    """
    from kb_init.cli import main

    _write_bundle(tmp_path)
    (tmp_path / "manifest.json").write_text("{不是 json", encoding="utf-8")
    (tmp_path / "knowledge").rmdir()
    assert main(["compile", str(tmp_path / "insights.md")]) == 4


@pytest.mark.parametrize("field", ["run_id", "corpus_hash"])
def test_identity_missing_on_both_sides_reports_9_not_traceback(tmp_path, field):
    """两边同时缺失时 None == None 会放行——那是拿缺失当共识。"""
    import json

    from kb_init.cli import main

    payload = _write_bundle(tmp_path)
    del payload[field]
    (tmp_path / "insights.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    del man[field]
    (tmp_path / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False), encoding="utf-8")
    assert main(["compile", str(tmp_path / "insights.md")]) == 9


# ---------------- 2C 报告 ----------------

def test_exit_10_when_report_failed(tmp_path, monkeypatch):
    from kb_init.cli import main

    summary = _fake_summary()
    summary["report_status"] = "failed"
    summary["report_reason"] = "render_failed"
    monkeypatch.setattr("kb_init.pipeline.run", lambda *a, **k: summary)
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 10


def test_exit_0_when_report_skipped(tmp_path, monkeypatch):
    """skipped 不是失败：--no-index 本来就没有洞察可渲染，
    给它报个错等于说「你用错了」，而那是一条一等公民的通道。"""
    from kb_init.cli import main

    summary = _fake_summary()
    summary["report_status"] = "skipped"
    summary["report_reason"] = "no_index"
    monkeypatch.setattr("kb_init.pipeline.run", lambda *a, **k: summary)
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 0


def test_compile_writes_share_report_and_prints_its_keywords(tmp_path, capsys):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    share = tmp_path / "report.share.html"
    assert share.exists()
    html = share.read_text(encoding="utf-8")
    assert "标题一" not in html, "证据标题不该进分享版"
    out = capsys.readouterr().out
    assert "report.share.html" in out
    assert "甲" in out and "乙" in out, "分享版包含的关键词必须打印给用户过目"


def test_share_render_failure_writes_nothing(tmp_path, monkeypatch):
    """渲染在写盘之前：渲染失败时档案与回执一个字节都没写。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    monkeypatch.setattr(
        "kb_init.report.render_share",
        lambda *a, **k: (_ for _ in ()).throw(OSError("渲染炸了")))
    assert main(["compile", str(tmp_path / "insights.md")]) == 4
    assert not (tmp_path / "knowledge" / "CLAUDE.md").exists()
    assert not (tmp_path / "compile.json").exists()
    assert not (tmp_path / "report.share.html").exists()


def test_share_write_failure_keeps_archive_and_is_rerunnable(tmp_path, monkeypatch):
    """分享版写盘失败 → 4，档案与回执完好，且**再跑一次能成功**（不卡住）。"""
    import kb_init.cli as mod
    from kb_init.cli import main

    _write_bundle(tmp_path)
    real = mod._write_share_report
    monkeypatch.setattr(
        mod, "_write_share_report",
        lambda *a, **k: (_ for _ in ()).throw(OSError("盘满了")))
    assert main(["compile", str(tmp_path / "insights.md")]) == 4
    assert (tmp_path / "knowledge" / "CLAUDE.md").exists()
    assert (tmp_path / "compile.json").exists()

    monkeypatch.setattr(mod, "_write_share_report", real)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    assert (tmp_path / "report.share.html").exists()


def test_share_report_leaves_no_tmp(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    main(["compile", str(tmp_path / "insights.md")])
    assert not (tmp_path / ".report.share.html.tmp").exists()


def test_refusal_warns_about_the_stale_share_report(tmp_path, capsys):
    """compile 拒绝产出时，必须提醒目录里还躺着上一次的分享版。

    用户取消勾选全部 → 退 8 什么都不写 → 上一次那份还在标准路径上，
    里面正是他刚撤掉的条目。**不删**（那是上一次的完好产物，删它撞硬不变量 #2），
    但不能不说：分享版是专门用来发出去的，档案没有这个问题，它有。
    """
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    share = tmp_path / "report.share.html"
    assert share.exists()

    _uncheck(tmp_path, "T1")
    capsys.readouterr()
    assert main(["compile", str(tmp_path / "insights.md")]) == 8
    err = capsys.readouterr().err
    assert "上一次" in err and "report.share.html" in err
    assert share.exists(), "不删——那是上一次成功运行的完好产物"


def test_no_stale_warning_when_there_is_no_share_report(tmp_path, capsys):
    """配对正例：没有旧分享版时不许瞎提醒，否则这条提示很快就没人看了。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    _uncheck(tmp_path, "T1")
    assert main(["compile", str(tmp_path / "insights.md")]) == 8
    assert "上一次" not in capsys.readouterr().err


def test_share_report_is_replaced_not_appended_on_rerun(tmp_path):
    """重跑之后，上一次勾选留下的内容不能还在分享版里。"""
    from kb_init.cli import main

    _write_bundle(tmp_path, insights=[
        _bundle_insight("T1", "topic", "topic_cluster",
                        {"doc_count": 9, "keywords": ["独有关键词甲"],
                         "share_of_kept": 0.03, "evidence_titles": []},
                        {"section": "focus_areas"}),
        _bundle_insight("T2", "topic", "topic_cluster",
                        {"doc_count": 4, "keywords": ["独有关键词乙"],
                         "share_of_kept": 0.01, "evidence_titles": []},
                        {"section": "focus_areas"}),
    ])
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    share = tmp_path / "report.share.html"
    assert "独有关键词乙" in share.read_text(encoding="utf-8")

    _uncheck(tmp_path, "T2")
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    text = share.read_text(encoding="utf-8")
    assert "独有关键词甲" in text
    assert "独有关键词乙" not in text, "取消勾选之后它不该还在分享版里"


@pytest.mark.parametrize("break_it,expected", [
    ("manifest", 7),
    ("schema", 9),
])
def test_stale_share_warning_covers_other_failure_codes(tmp_path, capsys,
                                                        break_it, expected):
    """提醒必须覆盖**每一个**非 0 出口。只覆盖 8/1 等于漏了一半。"""
    import json

    from kb_init.cli import main

    payload = _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    assert (tmp_path / "report.share.html").exists()

    if break_it == "manifest":
        (tmp_path / "manifest.json").write_text("{坏了", encoding="utf-8")
    else:
        payload["schema_version"] = "9.9"
        (tmp_path / "insights.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert main(["compile", str(tmp_path / "insights.md")]) == expected
    assert "上一次" in capsys.readouterr().err


def test_share_write_failure_says_the_archive_is_fine(tmp_path, monkeypatch, capsys):
    """笼统报「写入失败」会让人以为整件事都没成，去重跑一个已经完成的步骤。"""
    import kb_init.cli as mod
    from kb_init.cli import main

    _write_bundle(tmp_path)
    monkeypatch.setattr(mod, "_write_share_report",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("盘满了")))
    assert main(["compile", str(tmp_path / "insights.md")]) == 4
    err = capsys.readouterr().err
    assert "档案已写入" in err and "分享版" in err
    assert (tmp_path / "knowledge" / "CLAUDE.md").exists()


@pytest.mark.parametrize("cmd", ["validate", "compile"])
def test_missing_path_reports_not_found_not_usage_error(tmp_path, cmd, capsys):
    """路径打错时报「用法错误」是在指错方向：用法是对的，错的是文件不在。

    用户会去检查命令怎么写，而不是去看路径——报错码指错方向，人就会做错事。
    """
    from kb_init.cli import main

    assert main([cmd, str(tmp_path / "没有这个文件.md")]) == 7
    assert "找不到" in capsys.readouterr().err


@pytest.mark.parametrize("cmd", ["validate", "compile"])
def test_bare_subcommand_still_reports_usage(tmp_path, cmd, capsys):
    """配对正例：真的用法错误（没给参数）仍然是 2，不能被上一条吃掉。"""
    from kb_init.cli import main

    assert main([cmd]) == 2
    assert "用法" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--help", "-h", "--version"])
def test_subcommand_with_a_flag_is_not_treated_as_a_missing_path(tmp_path, flag,
                                                                  capsys):
    """`kb-init compile --help` 不该被报成「找不到 --help」。

    这是三审那条分流引入的回归：以 - 开头的参数是选项不是路径。
    """
    from kb_init.cli import main

    assert main(["compile", flag]) == 2
    assert "找不到" not in capsys.readouterr().err


def test_missing_path_diagnosis_does_not_depend_on_cwd(tmp_path, monkeypatch,
                                                        capsys):
    """当前目录里碰巧有个叫 compile 的东西时，诊断不该变。

    依赖 CWD 内容的行为差异是最难查的一类 bug：同一条命令在两个目录里给出
    两种回答，而用户不会想到去看当前目录里有什么。
    """
    from kb_init.cli import main

    (tmp_path / "compile").mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["compile", "没有这个文件.md"]) == 7
    assert "找不到" in capsys.readouterr().err


# ---------------- --agent-file ----------------

def test_archive_defaults_to_claude_md(tmp_path):
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    assert (tmp_path / "knowledge" / "CLAUDE.md").exists()


@pytest.mark.parametrize("name", ["AGENTS.md", "GEMINI.md", "context.md"])
def test_agent_file_writes_that_name(tmp_path, name):
    """Codex 读 AGENTS.md、Gemini 读 GEMINI.md——产出一个对方不读的文件，
    等于没产出。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", name]) == 0
    assert (tmp_path / "knowledge" / name).exists()
    assert not (tmp_path / "knowledge" / "CLAUDE.md").exists()


@pytest.mark.parametrize("bad", ["../escape.md", "sub/dir.md", "..", "",
                                 "/abs/path.md"])
def test_agent_file_rejects_anything_that_is_not_a_bare_filename(tmp_path, bad):
    """`--agent-file ../../x` 会把档案写到 knowledge/ 外面去。

    这个值来自命令行、要拼进路径，是一条真实的路径穿越面——而这个工具的
    输入本来就假定不可信（DESIGN R13 已为 zip 立过同样的规矩）。
    """
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", bad]) == 2
    assert not any((tmp_path / "knowledge").iterdir())


def test_receipt_records_the_actual_archive_name(tmp_path):
    """回执说的必须是盘上那份的名字，不能永远写 CLAUDE.md——
    产物不许撒谎，回执也是产物。"""
    import json

    from kb_init.cli import main

    _write_bundle(tmp_path)
    main(["compile", str(tmp_path / "insights.md"), "--agent-file", "AGENTS.md"])
    receipt = json.loads((tmp_path / "compile.json").read_text(encoding="utf-8"))
    assert receipt["archive_path"] == "knowledge/AGENTS.md"


def test_rerun_with_a_different_agent_file_does_not_touch_the_old_one(tmp_path):
    """换个名字重跑：旧的那份不该被动，因为它没在这次的授权范围里。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    main(["compile", str(tmp_path / "insights.md")])
    before = (tmp_path / "knowledge" / "CLAUDE.md").read_text(encoding="utf-8")
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", "AGENTS.md"]) == 0
    assert (tmp_path / "knowledge" / "CLAUDE.md").read_text(encoding="utf-8") == before


def test_validate_still_takes_exactly_one_argument(tmp_path):
    """配对守卫：给子命令加 flag 支持之后，validate 的用法不能跟着变松。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["validate", str(tmp_path / "insights.md")]) == 0
    assert main(["validate", str(tmp_path / "insights.md"), "--agent-file", "x"]) == 2


@pytest.mark.parametrize("bad", ["AGENTS.md.", "AGENTS.md ", "x.md:stream",
                                 "CON.md", "nul", "LPT1.md"])
def test_agent_file_rejects_windows_aliases(tmp_path, bad):
    """这三类在 Windows 上会别名到另一个目录项：写进去的和回执里记的不是
    同一个东西，而这个工具声称支持 Windows。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", bad]) == 2


def test_illegal_agent_file_does_not_leave_a_lock(tmp_path):
    """一个参数错误不该变成需要人去删文件才能解开的死结。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", "../x.md"]) == 2
    assert not (tmp_path / ".kb-init-compile.lock").exists()
    # 配对正例：改对之后照样能跑
    assert main(["compile", str(tmp_path / "insights.md")]) == 0


def test_receipt_for_another_archive_does_not_authorize_this_one(tmp_path):
    """换过 --agent-file 之后两份档案内容常常一模一样、哈希也一样——
    只比哈希的话，B 的回执会授权覆盖 A。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md")]) == 0
    claude = tmp_path / "knowledge" / "CLAUDE.md"
    before = claude.read_text(encoding="utf-8")
    # 现在回执描述的是 AGENTS.md
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", "AGENTS.md"]) == 0
    # 再回到 CLAUDE.md：回执说的不是它，必须拒绝
    assert main(["compile", str(tmp_path / "insights.md")]) == 1
    assert claude.read_text(encoding="utf-8") == before


def test_missing_path_with_options_still_says_not_found(tmp_path, capsys):
    """带 flag 时同样要报「找不到」而不是「用法错误」——
    上一轮刚修好的诊断，不能只修没有 flag 的那一半。"""
    from kb_init.cli import main

    assert main(["compile", str(tmp_path / "没有.md"), "--agent-file", "A.md"]) == 7
    assert "找不到" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["CON.tar.gz", "COM1.a.b", "nul.x.y"])
def test_windows_device_names_with_multiple_suffixes(tmp_path, bad):
    """Windows 认第一个点之前那一段——按 PurePath.stem 判会整个绕过去。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", bad]) == 2


def test_compile_does_not_delete_a_file_that_looks_like_our_temp(tmp_path):
    """档案名是用户给的：先用 --agent-file .AGENTS.md.tmp 生成一份，
    再用 --agent-file AGENTS.md 跑一次，固定临时名会把前一份静默删掉。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    victim = tmp_path / "knowledge" / ".AGENTS.md.tmp"
    victim.write_text("我自己的文件", encoding="utf-8")
    assert main(["compile", str(tmp_path / "insights.md"),
                 "--agent-file", "AGENTS.md"]) == 0
    assert victim.exists() and victim.read_text(encoding="utf-8") == "我自己的文件"


@pytest.mark.parametrize("cmd", ["compile", "validate"])
def test_directory_argument_points_at_insights_md(tmp_path, cmd, capsys):
    """给的是目录时，诊断要把人指向那个目录里的 insights.md，
    而不是让他去检查命令怎么写——命令是对的。"""
    from kb_init.cli import main

    _write_bundle(tmp_path)
    assert main([cmd, str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "insights.md" in err and "目录" in err
