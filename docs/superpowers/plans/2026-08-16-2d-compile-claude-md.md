# 2D `compile` → CLAUDE.md 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`
> 或 `superpowers:executing-plans`，按 Task 逐个执行。步骤用 `- [ ]` 勾选。

**Goal:** 实现 `kb-init compile <insights.md>`——按勾选状态与 `claude_md` 路由，
把用户审过的洞察正文编译成用户知识库的 `CLAUDE.md`。

**Architecture:** 纯管道。新模块 `claude_md.py` 持有 `SECTIONS` 表、结构 gate、
渲染纯函数与覆盖授权写盘；`cli.py` 只做 gate 编排与退出码映射；`insights.py` 改一个字段。

**Tech Stack:** Python 3.12 / pytest / 标准库（`hashlib` / `os` / `json`），无新依赖。

**Spec:** `docs/superpowers/specs/2026-08-16-2d-compile-claude-md-design.md`

> ⚠️ **本计划刻意只写接口签名 + 测试名 + 验收线，不内联完整实现。**
> 这是项目 CLAUDE.md 的流程校准，覆盖 writing-plans 的默认格式：2B 的计划内联了
> 3,134 行代码，而其中的实质部分（阈值、判据）在 TDD 中被实测反复推翻。
> 计划的价值是逼你先想清接口，不是预写代码。**看到没有实现代码不要以为计划不完整。**

## Global Constraints

- **硬不变量**（项目 CLAUDE.md 全文）：① 不加兜底路径 / 默认放行 / 内部专用开关；
  ② 失败不许带走已完成的产物；③ 不猜就是不猜，默认值也是猜；④ 产物不许撒谎；
  ⑤ 单元测试绝不下载模型。
- **检测器必须配负例**，且阈值不许取在正好让现状通过的位置。
- **断言写完先问「它有没有可能永远成立」。**
- 新增退出码：**8**（无可归档条目）/ **9**（`insights.json` 与本版代码不一致）。
  复用：**1**（拒绝覆盖）/ **4**（读写失败、锁被占用、`knowledge/` 缺失）。
- 档案正文**逐字**等于 `canonical_text`，不重新措辞；导语只能陈述对任何语料恒真的管道事实。
- 开源卫生：真实笔记标题与本机绝对路径不许进仓库；提交前 `git grep -nE "/Users/[A-Za-z0-9]" -- ':!CLAUDE.md'` 必须为空。
- 全量回归基线：**299 passed + 4 smoke**，不许退步。

## File Structure

| 文件 | 责任 |
|---|---|
| `src/kb_init/claude_md.py`（新） | `SECTIONS` / 结构 gate / 选择 / 渲染 / 授权与写盘。**档案与回执只由它写** |
| `src/kb_init/insights.py`（改） | 仅 `build_residual_insights` 里 R1 的 `claude_md` 字段 |
| `src/kb_init/cli.py`（改） | `compile` 子命令：gate 编排 + 退出码映射 |
| `tests/test_claude_md.py`（新） | 结构 gate / 选择 / 渲染 / 授权写盘的单元测试 |
| `tests/test_cli.py`（改） | `compile` 的端到端退出码测试 |
| `tests/test_insights.py`（改） | R1 路由去向的守卫测试 |
| `tests/test_real_corpus.py`（改） | 真实语料上的 compile 验收（语料不在则跳过） |
| `README.md` / `STATUS.md` / `docs/DESIGN.md`（改） | 用法、退出码、输出树、进度 |

---

### Task 1: R1 路由进档案线（2B 的一处改动）

先做这个：它独立、可单独合并，且是后面所有 `coverage` 节测试的前提。

**Files:**
- Modify: `src/kb_init/insights.py`（`build_residual_insights` 里 R1 的 `Insight(...)` 最后一个参数）
- Test: `tests/test_insights.py`

**Interfaces:**
- Produces: `R1` 的 `claude_md == {"section": "coverage"}`；`R2` 保持 `None`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_insights.py` 新增两条：

| 测试名 | 断言 |
|---|---|
| `test_r1_routes_to_coverage_section` | 构造 residual ≥ 3 的索引 → `R1.claude_md == {"section": "coverage"}` |
| `test_r2_stays_out_of_archive` | 同一构造 → `R2.claude_md is None`（负例：防止「把 residual 族整族路由过去」的实现蒙混过关） |

复用该文件里已有的索引构造 helper，不要新造语料。

- [ ] **Step 2: 跑测试确认失败**

`.venv/bin/python -m pytest tests/test_insights.py -q -k "routes_to_coverage or stays_out"`
预期：`test_r1_routes_to_coverage_section` FAIL（当前是 `None`）。

- [ ] **Step 3: 改字段**

只改 R1 那一个 `Insight(...)` 的最后一个位置参数，`canonical_text` / `payload` / 渲染器一律不动。

- [ ] **Step 4: 跑全量**

`.venv/bin/python -m pytest -q`
预期：全绿。特别确认 `test_corpus_insights_never_route_to_claude_md` 仍通过
（它断言的是 corpus 族，不该受影响；若它红了说明改错了地方）。

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/insights.py tests/test_insights.py
git commit -m "feat: R1 碎片区洞察路由进档案线（2D 的覆盖率缺口）"
```

---

### Task 2: `SECTIONS` 表与结构 gate

**Files:**
- Create: `src/kb_init/claude_md.py`
- Test: `tests/test_claude_md.py`

**Interfaces:**
- Produces:

```python
SECTIONS: tuple[tuple[str, str, str | None], ...]
# ("focus_areas", "关注领域", "按篇数排序。"), ("coverage", "这份档案的覆盖范围", None)
KNOWN_SECTIONS: frozenset[str]

class ArchiveContractError(ValueError): ...   # → 退出码 9
class ArchiveEmptyError(ValueError): ...      # → 退出码 8
class ArchiveOverwriteError(ValueError): ...  # → 退出码 1

def check_structure(payload: dict) -> None:
    """扫全量 insights，不合格即抛 ArchiveContractError。与勾选状态无关。"""
```

`check_structure` 的四项检查（spec §5.1）：`insight_id` 唯一 / 必需键齐备
（`insight_id` `family` `kind` `payload` `canonical_text` `claude_md`）/ `claude_md`
形状是 `None` 或恰好 `{"section": str}` / `section` 值在 `KNOWN_SECTIONS` 里。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_claude_md.py`，先写一个 `_payload(*insights, **top)` 构造 helper
（**fixture 纪律**：默认样本要含多语言关键词、含换行与多余空白的证据标题、
一条 `evidence_titles` 为空的条目——不要造「每条都长得一样」的规整数据，
2B 踩过太规整的 fixture 把好实现判成坏的）。

| 测试名 | 断言 |
|---|---|
| `test_check_structure_accepts_valid_payload` | 正例：合法 payload 不抛。**这是负例组的配对正例，缺它则恒抛错的实现也全绿** |
| `test_duplicate_insight_id_fails_closed` | 两条同 `insight_id` → 抛 |
| `test_missing_required_key_fails_closed` | 参数化删掉 6 个必需键中的每一个 → 各自抛 |
| `test_malformed_claude_md_shapes_fail_closed` | 参数化 `{}` / `{"section": None}` / `{"section": ""}` / `{"section": 7}` / `{"section": "focus_areas", "extra": 1}` → 各自抛 |
| `test_unknown_section_fails_closed` | `{"section": "blind_spots"}` → 抛 |
| `test_unknown_section_fails_even_when_unchecked` | 同上但该条**未勾选** → 仍抛（§5.1 的核心守卫：`check_structure` 根本不看勾选） |

- [ ] **Step 2: 跑测试确认失败**

`.venv/bin/python -m pytest tests/test_claude_md.py -q`
预期：全部 FAIL（`ModuleNotFoundError: kb_init.claude_md`）。

- [ ] **Step 3: 实现 `SECTIONS` + 三个异常类 + `check_structure`**

- [ ] **Step 4: 跑测试确认通过**

`.venv/bin/python -m pytest tests/test_claude_md.py -q` → 全绿。

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/claude_md.py tests/test_claude_md.py
git commit -m "feat: 档案线的 SECTIONS 表与结构 gate（扫全量，与勾选无关）"
```

---

### Task 3: 选择与渲染（纯函数）

**Files:**
- Modify: `src/kb_init/claude_md.py`
- Test: `tests/test_claude_md.py`

**Interfaces:**
- Consumes: Task 2 的 `SECTIONS` / `ArchiveContractError` / `ArchiveEmptyError`
- Produces:

```python
Grouped = list[tuple[str, list[dict]]]   # [(section_id, [insight, ...]), ...]

def select_for_archive(payload: dict, selections: dict[str, bool]) -> Grouped:
    """只收 selections[id] is True 且 claude_md is not None 的条目。
    节序按 SECTIONS，节内序按 payload["insights"] 数组序，空节不出现。
    一条都没有 → 抛 ArchiveEmptyError。"""

def verify_canonical_texts(grouped: Grouped) -> None:
    """对进档案的每一条断言 insights.render(Insight(...)) == canonical_text，
    不等即抛 ArchiveContractError。只校验进档案的，不校验全部。"""

def render_archive(payload: dict, grouped: Grouped) -> str:
    """逐字 canonical_text；证据行取 payload["evidence_titles"] 原字符串，只折叠空白。
    头部两行 HTML 注释含 run_id / corpus_hash / schema_version。"""
```

- [ ] **Step 1: 写失败测试**

| 测试名 | 断言 |
|---|---|
| `test_unchecked_items_are_excluded` | `selections["T2"] is False` → T2 不在结果里 |
| `test_null_claude_md_never_enters_archive` | corpus 族勾着也不进 |
| `test_section_and_item_order_follows_json` | 节序 `focus_areas` 先于 `coverage`；节内序等于数组序。**构造时故意把 coverage 条目放数组最前面**，否则这条断言可能永远成立 |
| `test_empty_selection_raises_empty` | 全不勾 → `ArchiveEmptyError` |
| `test_verify_canonical_detects_tampering` | 篡改一条 `canonical_text` → `ArchiveContractError` |
| `test_verify_canonical_passes_on_untampered` | 配对正例 |
| `test_verify_canonical_ignores_unarchived` | 篡改一条**未进档案**的 corpus 条目 → 不抛（守住「只校验进档案的」这条边界） |
| `test_body_is_canonical_text_verbatim` | 渲染结果中该行 `== f"- {canonical_text}"`，逐字，不含加粗/改写 |
| `test_evidence_line_folds_whitespace_only` | 含换行与连续空格的标题被折叠成单空格，**其余字符逐字保留** |
| `test_empty_evidence_titles_emits_no_evidence_line` | `evidence_titles` 为空 → 不产出「证据：」行（不产空行、不产「（无）」） |
| `test_lead_is_static_and_corpus_independent` | 用两份 `time_axis` 相反的 payload 渲染 → 导语字节相同（Codex 审 #7 的守卫） |
| `test_header_carries_identity` | 头部注释含 run_id / corpus_hash / schema_version |

- [ ] **Step 2: 跑测试确认失败** → `pytest tests/test_claude_md.py -q`

- [ ] **Step 3: 实现三个函数**

`verify_canonical_texts` 用 `from kb_init.insights import Insight, render`
重建 `Insight` 再比对；不要另写一份渲染逻辑（那就是第二个生成器，双载立刻失效）。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/claude_md.py tests/test_claude_md.py
git commit -m "feat: 档案的选择与渲染（逐字 canonical_text，节序与条目序不重排）"
```

---

### Task 4: 覆盖授权与写盘

本 Task 是 Codex 审 #1 的正面处置，测试比实现重要。

**Files:**
- Modify: `src/kb_init/claude_md.py`
- Test: `tests/test_claude_md.py`

**Interfaces:**
- Consumes: Task 2 的 `ArchiveOverwriteError`
- Produces:

```python
RECEIPT_NAME = "compile.json"
ARCHIVE_RELPATH = "knowledge/CLAUDE.md"
LOCK_NAME = ".kb-init-compile.lock"

def publish(out_dir: Path, payload: dict, text: str, insight_ids: list[str]) -> Path:
    """授权 → 写档案 → 写回执 → 释放锁。返回档案路径。

    授权三条全满足才允许替换（§5.2）：回执存在且 run_id 一致 /
    现存文件 sha256 等于回执所记 / 目标不是符号链接。
    """
```

写盘细节（spec §5.2 / §5.3）：

- `knowledge/` 不存在或不是目录 → `OSError`（**不创建**）；
- 锁：`os.open(out_dir/LOCK_NAME, O_CREAT|O_EXCL|O_WRONLY)`，`finally` 删除；
  已存在 → `OSError`，诊断给出锁文件路径。**不做超时自动清锁**；
- 新建路径：写 tmp 写满 → `os.link(tmp, target)`（原子且独占，目标已存在会抛）→ 删 tmp；
- 替换路径：写 tmp 写满 → `os.replace(tmp, target)`；
- 回执在档案之后写；回执写失败时**档案保留**，把 `OSError` 抛出去让 CLI 报 4。

- [ ] **Step 1: 写失败测试**

| 测试名 | 断言 |
|---|---|
| `test_writes_when_absent` | 目标不存在 → 写成功，回执生成，回执里的 sha256 与文件实际哈希相等 |
| `test_rerun_replaces_own_output` | 三条授权全满足 → 替换成功，内容更新为新文本 |
| `test_refuses_to_overwrite_foreign_file` | 无回执的同名文件（模拟一篇真叫 `CLAUDE.md` 的笔记）→ 抛 `ArchiveOverwriteError`，且**文件内容逐字未变** |
| `test_forged_marker_does_not_authorize` | 把 `<!-- kb-init:claude_md run_id=… -->` 复制进那篇假笔记、仍无回执 → 仍抛，内容未变 |
| `test_refuses_when_archive_hand_edited` | 回执在、run_id 对，但文件被追加过一行 → 抛，内容未变 |
| `test_refuses_when_receipt_from_other_run` | 回执 run_id 不同 → 抛 |
| `test_refuses_symlink_target` | 目标是指向另一文件的符号链接 → 抛，**被指向文件的内容未变** |
| `test_missing_knowledge_dir_is_error_not_created` | `knowledge/` 不存在 → 抛 `OSError`，且该目录**仍不存在** |
| `test_lock_blocks_concurrent_compile` | 预先建好锁文件 → 抛 `OSError`，档案未被改动 |
| `test_lock_released_on_success_and_on_failure` | 两种路径跑完，锁文件都不存在（负例：只测成功路径的话，`finally` 漏写不会被发现） |
| `test_no_tmp_left_behind` | 成功与失败路径跑完，`knowledge/` 下无 `.tmp` 残骸 |
| `test_receipt_write_failure_keeps_archive` | monkeypatch 让回执写盘抛 `OSError` → 档案仍在且内容是新的（硬不变量 #2） |

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 `publish` 与私有 helper**（`_read_receipt` / `_sha256` / `_lock`）

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/claude_md.py tests/test_claude_md.py
git commit -m "feat: 档案的覆盖授权（回执+哈希+拒符号链接+O_EXCL+锁）与原子写盘"
```

---

### Task 5: `compile` 子命令与退出码

**Files:**
- Modify: `src/kb_init/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 2–4 的全部公共函数与三个异常类
- Produces: `_compile_command(md_path: str) -> int`，并在 `main()` 里按与
  `validate` **相同**的特判接线（`len(argv) == 2 and argv[0] == "compile"
  and Path(argv[1]).is_file()`）。不引入 subparsers——那会弄坏 `kb-init <source>`
  的位置参数用法，`tests/test_cli.py` 有一条测试专盯这个。

gate 顺序**必须**与 spec §5 一致（1→14），尤其：

- 版本 gate（4）与身份 gate（5）**早于** `validate_markdown`（7）；
- 结构 gate（6）**早于** 过滤（9）。

退出码映射：`ArchiveContractError → 9` / `ArchiveEmptyError → 8` /
`ArchiveOverwriteError → 1` / `InsightsValidationError → 7` / `OSError → 4`。
manifest gate 与 `validate` 共用同一段逻辑与同一套四态拒绝（缺失 / 损坏 /
无该字段 / 顶层非对象）——**抽成一个函数给两个命令用**，不要复制粘贴：
两个读取入口两套标准，正是硬不变量 #1 点名的形态。

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli.py` 新增 `_write_bundle(tmp_path, ...)`（比现有 `_write_pair`
多写 `knowledge/` 目录，manifest 多写 `run_id` / `corpus_hash`）。

| 测试名 | 断言 |
|---|---|
| `test_compile_happy_path_writes_archive` | 返回 0，`knowledge/CLAUDE.md` 存在且含勾选条目的正文 |
| `test_compile_manifest_gate_four_states` | 四种坏 manifest → 各自 7（与 `validate` 同标准） |
| `test_compile_identity_mismatch_with_manifest` | manifest 的 `run_id` 或 `corpus_hash` 与 json 不符 → 9 |
| `test_compile_schema_version_mismatch` | json `schema_version` 与本版不符 → 9 |
| `test_stale_json_reports_9_not_7` | 旧 schema 的 json + 与之匹配的 md → **9 而不是 7**（顺序纪律的守卫；若实现把 validate 放前面，这条会红） |
| `test_compile_unknown_section_unchecked_reports_9_not_8` | 唯一可归档条目是未知 section 且未勾选 → **9 而不是 8**（§5.1 的守卫） |
| `test_compile_zero_archivable_writes_nothing` | 全不勾 → 8，且 `knowledge/CLAUDE.md` 不存在 |
| `test_compile_refuses_overwrite` | 预置一篇无回执的同名文件 → 1，内容未变 |
| `test_compile_missing_knowledge_dir` | 删掉 `knowledge/` → 4 |
| `test_compile_usage_error_without_file` | `kb-init compile` 无参数 → 2（与 `validate` 的用法错误对称） |
| `test_source_dir_named_compile_still_works` | 一个真叫 `compile` 的**目录**作为 source 仍按 source 处理（现有 `validate` 同款守卫，不许被新子命令弄坏） |

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 `_compile_command` + 抽出共用的 manifest gate**

- [ ] **Step 4: 跑全量**

`.venv/bin/python -m pytest -q` → 不低于 299 + 新增数，无退步。

- [ ] **Step 5: 提交**

```bash
git add src/kb_init/cli.py tests/test_cli.py
git commit -m "feat: kb-init compile 子命令与退出码 8/9"
```

---

### Task 6: 真实语料验收 + 文档 + 门面 gate

**Files:**
- Modify: `tests/test_real_corpus.py` / `README.md` / `STATUS.md` / `docs/DESIGN.md`

- [ ] **Step 1: 真实语料验收测试**

在 `tests/test_real_corpus.py` 加 `test_compile_on_real_corpus`（语料不在则
`pytest.skip`，沿用该文件现有的跳过写法）：跑完整链路 → 断言产物存在、
每一行正文都能在 `insights.json` 里找到逐字相同的 `canonical_text`、
产物中不含 `/Users/`。

- [ ] **Step 2: 跑两份语料，产物落仓库外**

```bash
.venv/bin/python -m kb_init ~/Documents/notion-export/Export-* -o /tmp/2d-notion
.venv/bin/python -m kb_init "~/Documents/Obsidian Vault/Archive/Apple Notes" -o /tmp/2d-apple
# 各自 compile 后把产物拷到 ~/Documents/assistant-output/kb-init-r2/
```

- [ ] **Step 3: 门面 gate（人肉，不进 CI）**

把两份产物给贾老师看，问一句「这个能不能拿出去给人看」。
**Apple Notes 那份预期不达标**（前两条是 2B spec §4.4 已声明的命名失效模式）——
提前记账，不当阻断项；处置是 2E 重命名，**不是回到 2B 对着这两份语料调参**。

- [ ] **Step 4: 更新文档**

- `README.md`：输出树加 `CLAUDE.md` 与 `compile.json`；退出码表加 8 / 9；
  新增「怎么生成 CLAUDE.md」一节（`kb-init compile my-kb/insights.md`）；
  已知限制补一条「档案的正文是审阅用语，因为它必须逐字等于你审过的那句话」。
- `STATUS.md`：2D 完成、门面产物状态、2E 的未了项。
- `docs/DESIGN.md` §6：把「关注领域按稳定性排序」标注为**时间轴可用时才成立**，
  当前降级为按篇数排序（否则设计文档与产物长期不一致）。

- [ ] **Step 5: 开源卫生检查 + 提交**

```bash
git grep -nE "/Users/[A-Za-z0-9]" -- ':!CLAUDE.md'   # 必须为空
git add -A && git commit -m "docs: 2D 的用法、退出码与验收记录"
```

---

## 收尾：Codex 终审

read-only + xhigh + **量化硬预算**（分钟数 + 点名禁止的探针行为 + 降级出口）。
**某轮零阻断即停**，不为求安心多跑一轮（2B 的收敛序列 9+4 → 3 → 2 → 1 → 0，
第 5 轮纯确认，是浪费）。

## Self-Review 记录

- **Spec 覆盖**：§3 纯管道 → Task 2/3；§4.2 逐字 → Task 3；§4.3 SECTIONS 与未知
  section → Task 2；§5 gate 序列 → Task 5；§5.1 结构 gate 前置 → Task 2 + Task 5；
  §5.2 授权 → Task 4；§5.3 I/O → Task 4；§6 退出码 → Task 5；§8 R1 → Task 1；
  §10 测试 → 各 Task；§11 验收 → Task 6。**无未覆盖条款。**
- **命名一致性**：`check_structure` / `select_for_archive` / `verify_canonical_texts` /
  `render_archive` / `publish` 五个名字在 Task 2–5 与 spec §9 中拼写一致；
  三个异常类名在 Task 2 定义、Task 3/4/5 引用，拼写一致。
- **占位符**：无 TBD / TODO；每条测试都写明了断言对象与它防的是什么。
