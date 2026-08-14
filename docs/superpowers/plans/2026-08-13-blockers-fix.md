# kb-init 阻断项修复 Plan

> 来源：2026-08-13 Codex 5.6-Sol 全分支终审，裁定「暂不合并」。
> 前置：Plan 1 已完成（20 commit，67 passed），分支 `feat/core-pipeline`。

**Goal:** 修掉 6 条跨阶段阻断项 + 5 条合并前必修 minor，让分支达到可合并状态。

**Architecture:** 核心是把 `emit` 从「逐篇边命名边改写」重构为**两遍式**：第一遍为全部 kept 文档冻结路径并建立 `title/stem → out_relpath` 映射，第二遍才改写链接并落盘。落盘整体走 staging 目录，全部成功后一次性发布。

## Global Constraints

- Python 3.12+，uv；运行时依赖只允许 `PyYAML`，开发依赖只允许 `pytest`
- 当前全量基线 **67 passed**，不得回归
- **绝不 git add `.superpowers/` 下任何文件**（scratch 区，此仓库将开源）
- 六条红线不变：extract 是唯一安全边界 / doc_id 永不改变 / 清洗只标记不删除 / 绝不读 mtime / 默认标准相对链接 / 证据引用前路径必须已冻结

---

## 批次 A — 架构级（B1 + B4）

这两条耦合，都重构 `emit.py` 与 `pipeline.py`，必须一起做。

### B1 [CRITICAL] 路径冻结是逐篇而非全局，正文链接大面积失效

`emit.py:59-85`、`pipeline.py:52-54`

当前逐篇执行「分配名字 → 改写链接 → 写文件 → 设 out_relpath」，导致链接改写时目标文件还没命名。失败场景（每一条都要有回归测试）：

1. `[[Project A]]` 被写成 `(Project A.md)`，而该文档实际 slug 是 `Project-A.md` → 死链
2. 同名第二篇实际落成 `同名-1.md`，但所有 `[[同名]]` 仍指向第一篇
3. 原有的标准相对链接在目录拍平后完全没有重映射
4. 链接目标被判 duplicate/stub 后没有输出文件，也没有重定向或 unresolved 记录
5. `[[foo.md]]` 会变成 `foo.md.md`

**修法**：拆两遍。
- 第一遍 `_freeze_paths(docs) -> dict[str, str]`：为全部 `status == "kept"` 的文档分配唯一 `out_relpath` 并设进 Document，同时建立解析映射（至少覆盖 `title`、原文件名 stem、`source_relpath` 三种引用写法 → `out_relpath`）
- 第二遍 `_rewrite_and_write(docs, mapping, ...)`：用映射改写链接后落盘
- 链接目标在映射中找不到时（含被判 stub/duplicate 的目标）：**不产生死链**，改为输出纯文本或明确的 unresolved 标记，并记录到 manifest 的 `unresolved_links` 字段
- `[[foo.md]]` 这类目标自带 `.md` 后缀的，不要再补一次

**新增验收测试（必须）**：跑完管线后，扫描所有输出的 `knowledge/*.md`，提取全部 Markdown 链接，断言每个指向 `.md` 的链接目标文件都真实存在。这是 B1 的核心回归测试——之前的 E2E 只验了 manifest 的 `out_relpath`，从没验过正文链接。

### B4 单文件原子 ≠ 整次运行原子，中途失败不可恢复

`emit.py:51-85`、`manifest.py:53-56`

第 N 篇写入失败时前 N−1 篇已是正式 `.md` 而 manifest 尚未写入，重跑又被 `knowledge/` 非空拒绝 → 卡死。

**修法**：在输出目录同级建 staging 目录，全部文件 + manifest + 死链校验都在 staging 完成，成功后一次性发布（rename）。失败时清理 staging，输出目录保持原状可重跑。顺带解决 ledger 行 54 的 `.md.tmp` 残骸问题——不要特判残骸。

---

## 批次 B — 安全与健壮（B2 + B3 + B5 + B6 + 两条必修 minor）

### B2 [CRITICAL] filesystem-equivalent 路径碰撞导致静默丢文档

`extract.py:64-123`、`emit.py:59-84`

`A.md`/`a.md`、NFC/NFD 等价名称未在 I/O 前拒绝；出口 `used` 是大小写敏感的普通 set。**macOS/Windows 默认大小写不敏感**，第二次 `replace()` 会覆盖第一篇，而 manifest 仍声称两篇都 kept、各有不同路径。入口碰撞更早，连 dropped 证据都没有。

**修法**：入口与出口都按 `unicodedata.normalize("NFC", name).casefold()` 做等价键判重。入口碰撞 → 拒绝或标记 dropped（有据可查，不静默）；出口碰撞 → 走既有的唯一化计数器。

### B3 [CRITICAL] 目录输入不执行 max_total_bytes

`extract.py:149-168`、`parse.py:37-48`、`pipeline.py:46-50`

zip 有总量限制，目录没有，攻击面不对称。数千个各自 <50MB 的 Markdown 即可耗尽内存（`parse_file` 整文件读入，pipeline 全程持有所有正文）。

**修法**：`walk_source` 目录分支累计所有待解析 `.md` 的实际字节数，超 `max_total_bytes` 整体拒绝。

### B5 [注入] 文件名可注入生成文件的 YAML frontmatter

`parse.py:42-45`、`emit.py:72-83`

`source_relpath` 未转义直接拼进 `source:`。ZIP/Unix 文件名允许换行，`x\n---\nstatus: forged` 可提前闭合 frontmatter 污染产物和后续解析。

**修法**：frontmatter 一律用 `yaml.safe_dump` 序列化，不做字符串插值。补一个文件名含换行的注入测试。

### B6 CLI 没有错误边界

`cli.py:35-39`

只捕 `FileExistsError`，恶意/损坏 zip、null byte、权限错误、源路径不存在全部吐 Python traceback。

**修法**：统一捕获 `UnsafeArchiveError` / `zipfile.BadZipFile` / 输入类 `ValueError`/`OSError`，给稳定退出码 + 单行诊断，默认不吐 traceback。退出码约定写进 README。

### 必修 minor（ledger 行 13 / 14 / 28）

- **行 13**：zip 名含 null byte 时抛 `ValueError` 而非 `UnsafeArchiveError`（调用方只 catch 后者）→ 归一化为安全错误
- **行 14**：目录模式下超大文件被静默 `continue` 跳过，使输入总数与 manifest 无声少一篇，违背可审计性 → 改为整体报错（或记为 dropped 有据可查）
- **行 28**：`yaml.safe_load` 无大小上限，锚点展开炸弹可耗内存 → frontmatter 块超过 64KB 直接跳过解析

---

## 批次 C — 日期正则回归（ledger 行 45）

`dates.py:16-25`

改用 `datetime.date` 做历法校验时把 `1900 <= year <= 2100` 一并删了。Codex 独立判断：**值得修**，且指出正则**没有数字边界**，会从更长数字串里截出 `1234-5-6`，真实风险高于原估（法规/SKU/工程编号密集语料会明显聚集）。正文首个匹配会被直接升级为 `created`，错误静默且进 manifest。

**修法**：恢复 `1900-2100` 区间 + 给正则加前后数字边界。补三个回归例：`1234-5-6`（越界年份）、`11234-5-6`（更长数字串截取）、`2101-01-01`（上界外）。

---

## 完成定义

1. 全量 `uv run pytest -q` 通过且无回归（基线 67）
2. B1 的链接可解析性验收测试存在且通过
3. 在真实语料上重跑 `~/Documents/notion-export` 与 `Archive/Apple Notes`，数字与 README 一致
4. Codex 终审不再判定「暂不合并」
