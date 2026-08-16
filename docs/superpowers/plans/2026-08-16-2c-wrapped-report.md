# 2C Wrapped 报告 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`
> 或 `superpowers:executing-plans`，按 Task 逐个执行。

**Goal:** `report.private.html`（主 run）+ `report.share.html`（compile）——
把 DESIGN §4.2 那个「Wrapped 是档案的验收界面」的闭环接上。

**Architecture:** `report.py` 只产字符串不碰磁盘；私有版写进 staging 随 rename 发布；
分享版在 compile 末尾原子写入 out_dir 根目录，**不进 2D 的 publish 事务**。

**Tech Stack:** Python 3.12 / pytest / 标准库（`html.escape`），无新依赖、无 JS、无外链。

**Spec:** `docs/superpowers/specs/2026-08-16-2c-wrapped-report-design.md`

> ⚠️ **本计划只写接口签名 + 测试名 + 验收线，不内联完整实现**（项目 CLAUDE.md 的流程校准，
> 覆盖 writing-plans 默认格式）。看到没有实现代码不要以为计划不完整。

## Global Constraints

- **硬不变量**：① 不加兜底路径；② 失败不许带走已完成的产物；③ 不猜就是不猜；
  ④ 产物不许撒谎；⑤ 单元测试绝不下载模型。
- **检测器必须配负例**；**断言写完先问「它有没有可能永远成立」**。
- 报告的断言性文字 **逐字**等于 `canonical_text`；**零生成式文案**。
- 报告无 JS、无外链、单文件自包含；CSP `default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'`。
- 新增退出码 **10**（报告未生成）；`skipped` 不算失败，仍返回 0。
- 开源卫生：`git grep -nE "/Users/[A-Za-z0-9]" -- ':!CLAUDE.md'` 必须为空。
- 回归基线：**417 passed + 5 smoke**，不许退步。

## File Structure

| 文件 | 责任 |
|---|---|
| `src/kb_init/report.py`（新） | 转义 / 条形宽度 / 模板 / 两种视图渲染。**纯函数，不写盘** |
| `src/kb_init/pipeline.py`（改） | `_run_report_stage`，照抄 `_run_insights_stage` 的失败纪律 |
| `src/kb_init/manifest.py`（改） | `report_status` / `report_reason` |
| `src/kb_init/cli.py`（改） | 退出码 10；compile 末尾写分享版 + 打印关键词 |
| `tests/test_report.py`（新） | 渲染 / 转义 / allowlist / 条形的单元测试 |
| `tests/test_cli.py`、`tests/test_index_pipeline.py`（改） | 退出码与阶段状态 |
| `README.md` / `STATUS.md` / `docs/DESIGN.md`（改） | 输出树、退出码、进度 |

---

### Task 1: `report.py` 的地基——转义与条形宽度

先做这两个纯函数：它们是 XSS 与「产物不撒谎」两条防线的落点，且不依赖任何上游。

**Files:** Create `src/kb_init/report.py` / Create `tests/test_report.py`

**Interfaces:**

```python
class ReportContractError(ValueError): ...   # 渲染期的合同违例

def esc(value: str) -> str:
    """唯一的 HTML 转义入口。模板里不允许出现未经它的插值。"""

def bar_width(part: int | float, whole: int | float) -> str:
    """条形宽度百分比，固定一位小数、钳位 [0,100]。

    唯一进入 CSS 的值。非有限值（NaN/inf）与非数字一律抛 ReportContractError,
    不静默取 0——取 0 是猜。whole 为 0 时返回 "0.0"。
    """
```

| 测试名 | 断言 |
|---|---|
| `test_esc_neutralizes_tag_and_attr_breakouts` | `<`/`>`/`&`/`"`/`'` 全部转义 |
| `test_esc_leaves_normal_text_alone` | 配对正例：中英文正常文本不被改动（防「转义成乱码」） |
| `test_bar_width_is_proportional_from_zero` | 两个宽度之比 == 两个篇数之比（截断坐标轴即红） |
| `test_bar_width_clamps` | 负数 → `"0.0"`；超出 whole → `"100.0"` |
| `test_bar_width_rejects_non_finite` | `float("nan")` / `inf` / `"29"` → 抛 `ReportContractError` |
| `test_bar_width_zero_whole` | `whole == 0` → `"0.0"`，不抛除零 |

TDD 五步：写测试 → 跑红 → 实现 → 跑绿 → 提交
（`git commit -m "feat: 报告的转义与条形宽度（唯一进 CSS 的值）"`）。

---

### Task 2: 私有版渲染

**Files:** Modify `src/kb_init/report.py` / `tests/test_report.py`

**Interfaces:**

```python
SECTION_TITLES = {"topic": "主题", "residual": "碎片区", "corpus": "语料"}
NEXT_STEP_TEXT = "…"   # 静态常量：打开 insights.md 取消勾选，再跑 kb-init compile

def render_private(payload: dict) -> str:
    """全量渲染。每条带短 ID、canonical_text 逐字、关键词 chip、条形、证据行。"""
```

| 测试名 | 断言 |
|---|---|
| `test_every_insight_appears_with_its_id` | 每条的短 ID 都在报告里（呈现层与操作层的接缝） |
| `test_assertive_text_is_canonical_verbatim` | 每条 `canonical_text` 逐字出现 |
| `test_report_contains_no_unexplained_assertion` | 计数比对：除模板常量外，每个断言片段都能追溯到 payload（同 2D 的「一行都不能多」，用 `Counter`，**不是集合**） |
| `test_script_tag_in_title_is_escaped` | 标题含 `<script>alert(1)</script>` → 报告里无可执行标签，只有实体 |
| `test_script_tag_in_keyword_is_escaped` | 关键词同样来自语料，同样要转义 |
| `test_bare_url_in_title_is_not_linkified` | 裸 URL 是纯文本，没被自动变链接 |
| `test_no_reference_constructs` | 不含 `src=` / `href=` / `<script` / `@import` / `url(`。**判据是构造不是子串 `http`**——真实证据标题里就含裸 URL |
| `test_csp_meta_present` | CSP meta 存在且含四项指令 |
| `test_next_step_block_present` | 「下一步」块在（报告是验收界面，看完不知道干什么闭环照样断） |
| `test_sections_follow_family_order` | 主题 → 碎片区 → 语料；节内序 == `insights` 数组序 |

---

### Task 3: 分享版与 allowlist

**Files:** Modify `src/kb_init/report.py` / `tests/test_report.py`

**Interfaces:**

```python
SHARE_ALLOWED_PAYLOAD_KEYS = frozenset({"doc_count", "share_of_kept", "count",
                                        "keywords", "total", "kept", ...})
SHARE_DISCLOSURE = "…"   # 静态常量：本文件包含什么、不包含什么

def render_share(payload: dict, selections: dict[str, bool]) -> str:
    """只收勾选过的条目 ∩ allowlist 字段。**从零构造**，不是「拿私有版删几处」。"""

def share_keywords(payload: dict, selections: dict[str, bool]) -> list[str]:
    """分享版里出现的全部关键词，供 CLI 打印给用户过目。"""
```

| 测试名 | 断言 |
|---|---|
| `test_share_omits_every_denied_field` | 参数化：证据标题 / doc_id / run_id / corpus_hash / naming.params 各自不出现 |
| `test_share_keeps_allowed_fields` | 配对正例：关键词与数字仍在（否则「全删掉」也能让上一条全绿） |
| `test_share_only_contains_checked_items` | 取消勾选的条目不进；**且它的关键词也不在** |
| `test_share_disclosure_present` | 文件里可见地声明包含/不包含什么 |
| `test_share_is_built_from_scratch_not_filtered` | 私有版新增一个未列入 allowlist 的字段 → 它**不会**自动出现在分享版（守住「从零构造」而不是「删几处」） |
| `test_share_keywords_lists_exactly_what_appears` | `share_keywords()` 的结果与分享版里实际出现的关键词集合相等 |

---

### Task 4: 主 run 产私有版

**Files:** Modify `src/kb_init/pipeline.py`、`src/kb_init/manifest.py`、`tests/test_index_pipeline.py`

**Interfaces:**

```python
def _run_report_stage(staging: Path, *, insights_status: str) -> tuple[str, str | None]:
    """照抄 _run_insights_stage 的形状。**异常绝不允许放出去**——
    放出去会穿到 run() 的 finally，把清洗产物、索引、洞察一起删掉。
    """
```

位置：洞察阶段之后、最终 `write_manifest` 之前。`summary["report_status"]` 随其余状态返回。

| 测试名 | 断言 |
|---|---|
| `test_report_written_into_staging_and_published` | 正常路径：`out_dir/report.private.html` 存在，`report_status == "complete"` |
| `test_report_failure_keeps_all_prior_products` | 渲染抛错 → `knowledge/`、`index.json`、`insights.*` **全在**，`report_status == "failed"` |
| `test_report_stage_never_raises` | 渲染与清理都抛错 → 函数仍正常返回，`reason == "io_failed"` |
| `test_report_skipped_without_index` | `--no-index` → `skipped` / `no_index` |
| `test_report_skipped_when_insights_failed` | 洞察失败 → `skipped` / `insights_failed` |

---

### Task 5: 退出码 10 与 compile 侧的分享版

**Files:** Modify `src/kb_init/cli.py`、`tests/test_cli.py`

顺序（spec §7.2）：渲染档案与分享版（纯内存）→ `publish(档案)`（2D 原样）→ 原子写分享版。

| 测试名 | 断言 |
|---|---|
| `test_exit_10_when_report_failed` | `report_status == "failed"` → 10 |
| `test_exit_0_when_report_skipped` | `skipped` → **0**（skipped 不是失败） |
| `test_compile_writes_share_report` | compile 后 `out_dir/report.share.html` 存在 |
| `test_compile_prints_share_keywords` | stdout 里列出了分享版包含的全部关键词 |
| `test_share_render_failure_writes_nothing` | 渲染失败 → 档案与回执**一个字节都没写** |
| `test_share_write_failure_keeps_archive_and_is_rerunnable` | 写盘失败 → 4，档案与回执完好，**再跑一次能成功** |

---

### Task 6: 真实语料 + 文档 + 门面 gate

- `tests/test_real_corpus.py`：两份语料端到端，断言报告存在、无 `/Users/`、每条 ID 都在；
- 跑两份语料，产物落 `~/Documents/assistant-output/kb-init-r2/`；
- **门面 gate（人肉）**：贾老师打开私有版，能说出「我要取消勾选哪几条」——
  这是这份报告唯一的功能测试；分享版拿给第三个人看，看不出是谁的知识库；
- README（输出树 + 退出码 10 + 两份报告的用途）/ STATUS / DESIGN §10 对齐；
- 开源卫生检查 + 提交。

## 收尾：Codex 终审

read-only + xhigh + 量化硬预算。**某轮零阻断即停。**

## Self-Review 记录

- **Spec 覆盖**：§2.1 ID 桥 → Task 2；§2.2 时序 → Task 4/5；§3 逐字 → Task 2；
  §4 排版与条形 → Task 1/2；§5 allowlist → Task 3；§6 XSS → Task 1/2；
  §7.1 私有版失败 → Task 4；§7.2 分享版失败 → Task 5；§10 测试 → 各 Task；§11 验收 → Task 6。
- **命名一致性**：`esc` / `bar_width` / `render_private` / `render_share` / `share_keywords` /
  `_run_report_stage` 在各 Task 与 spec §8 中拼写一致。
- **占位符**：`SHARE_ALLOWED_PAYLOAD_KEYS` 与 `NEXT_STEP_TEXT` / `SHARE_DISCLOSURE` 的**具体值**
  留到实现时定——它们是文案与字段清单，spec §4/§5 已给出内容要求；
  计划里写死反而会在 TDD 中被推翻（2B 的教训）。
