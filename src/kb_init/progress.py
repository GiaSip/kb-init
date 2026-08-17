"""首跑体验：把索引阶段正在干什么说出来。

DESIGN R14 记着「首次运行不是秒开」——冷启动要下载约 90MB 模型、按分钟计，
而在这之前用户看到的是一片空白。一个盯着空白终端的人会怀疑它挂了，然后 Ctrl-C，
于是这个工具在他那里的唯一一次机会就没了。

**一条特别的纪律：不猜。** 不报剩余时间、不报百分比——我们没有可靠的估计依据，
编一个就是产物在撒谎（硬不变量 #3 / #4）。R14 处方里的「预估时间」据此降级为
「预先告知量级」：「首次运行需下载约 90MB，按分钟计」是已知事实，
「还剩 3 分钟」不是。

进度**全部走 stderr**：stdout 留给结果，`kb-init … | jq` 不该被进度污染。
"""
from __future__ import annotations

import sys

# 每多少条向量说一次。适配器已经按 200 条节流过一次，这里再按行数收一次口，
# 免得两万篇的语料刷出上百行——刷屏与静默是同一个病的两端。
_EMBED_LINES_MAX = 10


class ProgressPrinter:
    """索引阶段的进度消费者。

    `tty` 目前只用于将来可能的差异化输出；即使在终端里也**不使用 `\\r`**
    覆盖式刷新——那在日志与 `2>` 重定向里会变成一堆控制字符，而这个工具的
    输出经常要贴给别人看。
    """

    def __init__(self, tty: bool | None = None, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._tty = sys.stderr.isatty() if tty is None else tty
        self._last_said = 0
        self._embed_step = 0

    def _say(self, text: str) -> None:
        print(text, file=self._stream, flush=True)

    def __call__(self, event: dict) -> None:
        """进度是附属品，绝不能拖垮主流程——认不出的事件一律忽略。

        这里的「忽略」不是兜底路径：它不让任何规则失效，只是让一个纯展示层
        对上游新增事件保持沉默，而不是把整次运行炸掉。
        """
        kind = (event or {}).get("event")
        if kind == "model_loading":
            self._say("正在准备向量模型（首次运行需下载约 90MB，按分钟计；"
                      "之后会用本地缓存）…")
        elif kind == "embedding":
            self._on_embedding(event)
        elif kind == "clustering":
            self._say("正在按主题聚类…")

    def _on_embedding(self, event: dict) -> None:
        done, total = event.get("done"), event.get("total")
        if not isinstance(done, int) or not isinstance(total, int) or total <= 0:
            return
        if self._embed_step == 0:
            # 按总量算出间隔，而不是取固定值：固定间隔在小语料上一条都不说，
            # 在大语料上又刷屏。
            self._embed_step = max(1, total // _EMBED_LINES_MAX)
        # 判据是「距上次说过去了多远」，不是 `done % step == 0`——后者依赖
        # 上游恰好按某个步长发事件，上游一改步长就可能一条都对不上、彻底静默。
        # 而静默正是这一整层要解决的问题，用一个会静默失效的判据去解它，
        # 等于没解。
        if done < total and done - self._last_said < self._embed_step:
            return
        self._last_said = done
        self._say(f"正在计算向量 {done}/{total}…")
