# kb-init — 项目上下文

把笔记导出（Notion / Apple Notes）一次性编译成两样东西：一份可分享的知识报告，
和一份 AI agent 能直接用的 `CLAUDE.md`。Python 3.12 + uv，即将开源。

## 先读哪几份

| 想知道 | 读 |
|---|---|
| 现在做到哪、下一步是什么 | `STATUS.md` |
| 为什么这么设计、哪些是已裁决的 | `docs/DESIGN.md`（§4.2 验收闭环 / §4.3 IR 合同 / §5 洞察分层 / §12 链接语义 / §13 R2 验收） |
| 当前在做的子项目 | `docs/superpowers/specs/` 最新一份 |

Plan 2 拆成五块：**2A 索引**（已合并）→ **2B L2 洞察 + insights 合同** → 2D compile → 2C Wrapped → 2E L3。

## 硬不变量（都是付过代价换来的，改动前先读）

1. **绝不产出「活着的错链」。** 死链有人报，错链没人查。链接解析只按当前文档所在目录
   （CommonMark），不按 basename 跨目录兜底，不"这个基准不中就换一个再试"。歧义一律降级。
   → 教训：只要还留一条兜底路径，"歧义不猜"就会被它绕过。**加兜底前先问它会不会指错。**
2. **失败不许带走已完成的产物。** 索引失败在 pipeline 内被吸收成状态（`manifest.index_status`），
   CLI 在 `run()` **正常返回后**映射退出码 5。commit 点之后不做任何可能失败的事——
   返回值提前算好、临时目录提前清掉。
3. **不猜就是不猜。** 日期解析不到标 `unknown`，聚类归不了标 `residual`，
   时间轴覆盖率不够就整个关掉。宁可少给一条，不给一条看不出是什么的。
4. **产物不许撒谎。** 分块降级了要记 `fallback_used`，注入的是假 embedder 就不能写 fastembed，
   `coverage` 必须由 assignments 派生而不是独立计数。
5. **单元测试绝不下载模型**；fastembed / sklearn 一律惰性导入，模块顶层禁止。

## 这个项目上最贵的两个教训

- **合成语料测不出真实形态。** 链接层合成测试全绿时，真实 Notion 语料 288 条内部链接 100% 死链。
  **任何链接 / 路径 / 分块类的改动，验收必须跑真实语料**（路径见 `STATUS.md` 语料资产表）。
- **断言可能恒真。** tokenizer 自带截断时，"每块 ≤512 token"这条断言永远通过，
  分块器其实完全没在分块。**写完断言先问：它有没有可能永远成立？**

## 怎么跑

```bash
.venv/bin/python -m pytest -q            # 全量（含真实语料验收，语料不在则自动跳过）
.venv/bin/python -m pytest -q -m smoke   # 真实模型烟测，需已预热模型缓存
uv sync                                   # 改了依赖之后
```

改动流程走 superpowers：brainstorming → writing-plans → TDD 实现 → Codex 终审 → 合并。
Codex 终审用 read-only + xhigh + **量化硬预算**（分钟数 + 点名禁止的探针行为 + 降级出口），
没有硬预算它会把时间烧在无界探测上。

## 开源卫生

`.superpowers/` 是 scratch 区且已 gitignore，**绝不能进历史**（报告含本机绝对路径）。
提交前确认 `git grep "/Users/"` 无命中。
