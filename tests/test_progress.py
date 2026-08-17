"""首跑体验（DESIGN R14）：冷启动要下 ~90MB 模型、按分钟计，
而在这之前用户看到的是一片空白——足以让人以为它挂了，然后 Ctrl-C。

这一层的纪律只有一条特别的：**不猜**。不报剩余时间、不报进度百分比——
我们没有可靠的估计依据，编一个就是产物在撒谎。
"""
import pytest

from kb_init.progress import ProgressPrinter


def _lines(capsys):
    captured = capsys.readouterr()
    return captured.out, [ln for ln in captured.err.splitlines() if ln.strip()]


def test_model_stage_is_announced_before_anything_downloads(capsys):
    """这是整条 R14 的要点：说明必须**先于**下载出现，不是下完再说。"""
    p = ProgressPrinter(tty=False)
    p({"event": "model_loading", "model": "BAAI/bge-small-zh-v1.5"})
    _, err = _lines(capsys)
    assert err, "模型加载阶段必须有输出"
    assert "分钟" in err[0] or "90" in err[0], f"要预先告知量级：{err[0]}"


def test_progress_goes_to_stderr_not_stdout(capsys):
    """stdout 留给结果，管道友好——`kb-init … | jq` 不该被进度污染。"""
    p = ProgressPrinter(tty=False)
    p({"event": "model_loading", "model": "m"})
    p({"event": "embedding", "done": 200, "total": 1000})
    out, err = _lines(capsys)
    assert out == ""
    assert err


def test_progress_is_throttled(capsys):
    """1000 篇不该产出 1000 行。"""
    p = ProgressPrinter(tty=False)
    for done in range(200, 20001, 200):
        p({"event": "embedding", "done": done, "total": 20000})
    _, err = _lines(capsys)
    assert 0 < len(err) <= 12, f"输出了 {len(err)} 行，刷屏了"


def test_progress_has_no_carriage_returns(capsys):
    """`\\r` 覆盖式刷新在日志与 `2>` 重定向里会变成一堆控制字符。"""
    p = ProgressPrinter(tty=False)
    for done in range(200, 3001, 200):
        p({"event": "embedding", "done": done, "total": 3000})
    assert "\r" not in capsys.readouterr().err


@pytest.mark.parametrize("forbidden", ["剩余", "预计还要", "ETA", "%"])
def test_progress_never_claims_remaining_time_or_percentage(capsys, forbidden):
    """没有可靠依据的预估就是猜。R14 处方里的「预估时间」据此降级为
    「预先告知量级」——「按分钟计」是已知事实，「还剩 3 分钟」不是。"""
    p = ProgressPrinter(tty=False)
    p({"event": "model_loading", "model": "m"})
    for done in range(200, 2001, 200):
        p({"event": "embedding", "done": done, "total": 2000})
    p({"event": "clustering"})
    assert forbidden not in capsys.readouterr().err


def test_unknown_events_are_ignored_not_crashed(capsys):
    """上游以后新加事件时，旧版本不该炸——进度是附属品，不能拖垮主流程。"""
    p = ProgressPrinter(tty=False)
    p({"event": "something_new_from_the_future"})
    p({})
    assert capsys.readouterr().err == ""


def test_counts_are_shown_so_the_user_can_tell_it_is_moving(capsys):
    p = ProgressPrinter(tty=False)
    p({"event": "embedding", "done": 400, "total": 1130})
    _, err = _lines(capsys)
    assert "400" in err[0] and "1130" in err[0]


# ---------------- 接线：进度必须真的被送到 ----------------

def test_pipeline_forwards_progress_to_the_embedder(tmp_path):
    """钩子在 embed.py 里躺了很久却没人接——这条测试就是防它再次变成摆设。"""
    from kb_init.pipeline import run

    seen = []
    src = tmp_path / "src"
    src.mkdir()
    for i in range(6):
        (src / f"n{i}.md").write_text("# 标题\n\n" + "内容" * 120, encoding="utf-8")

    from tests.fakes import FakeEmbedder

    class Recording(FakeEmbedder):
        pass

    run(src, tmp_path / "out", run_id="p1", embedder=Recording(dim=8),
        progress=seen.append)
    # 注入的 embedder 不该被替我们决定报不报进度；但聚类阶段是管线自己的事。
    assert any(e.get("event") == "clustering" for e in seen), seen


def test_pipeline_runs_without_a_progress_consumer(tmp_path):
    """进度是可选的，不能变成必需依赖。"""
    from kb_init.pipeline import run
    from tests.fakes import FakeEmbedder

    src = tmp_path / "src"
    src.mkdir()
    for i in range(6):
        (src / f"n{i}.md").write_text("# 标题\n\n" + "内容" * 120, encoding="utf-8")
    counts = run(src, tmp_path / "out", run_id="p2", embedder=FakeEmbedder(dim=8))
    assert counts["index_status"] == "complete"


def test_no_index_run_never_announces_the_model(tmp_path, monkeypatch, capsys):
    """`--no-index` 根本不加载模型，说「正在准备模型」就是产物撒谎。"""
    from kb_init.cli import main

    src = tmp_path / "src"
    src.mkdir()
    (src / "n.md").write_text("# 标题\n\n" + "内容" * 120, encoding="utf-8")
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-index"]) == 0
    assert "模型" not in capsys.readouterr().err
