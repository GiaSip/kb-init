# 2B L2 洞察层（含前置 2A′）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2A 的索引事实编译成 12–20 条人能逐条勾选的洞察，冻结 `insights.json` / `insights.md` 两份下游合同；并按已触发的回头条件补一段过大簇细分。

**Architecture:** 先加 2A′（内聚度检测器 + `analyses[1]` 二次细分，主分析零改动），再加洞察层（读回索引 → 三族洞察 → 两份产物）。洞察层在 pipeline 内以窄边界运行，失败被吸收成 `manifest.insights_status`，CLI 在 `run()` 正常返回后映射退出码 6。

**Tech Stack:** Python 3.12 / numpy / scikit-learn（均已在依赖里，**本计划不新增任何依赖**）/ pytest / uv

**Spec:** `docs/superpowers/specs/2026-08-15-2b-insights-layer-design.md`

## Global Constraints

从 spec 逐条抄下，**每个任务的要求都隐含包含本节**：

- **单元测试绝不下载模型。** fastembed / sklearn 一律惰性导入，模块顶层禁止 `import sklearn`。
- **绝不产出「活着的错链」**，歧义一律降级；不加任何"这个基准不中就换一个再试"的兜底路径。
- **失败不许带走已完成的产物。** 洞察失败在 pipeline 内被吸收成状态，commit 点（`staging.rename`）之后不做任何可能失败的事。
- **不猜就是不猜。** 条件不成立的洞察**不产出**，不产出占位条目。
- **产物不许撒谎。** 所有阈值与参数随产物落盘；`counts` 必须由 `insights` 数组派生而非独立计数。
- **`analyses[0]` 一个字节都不改**（2A′ 只追加 `analyses[1]`）。
- **断言不许恒真。** 每条"集合 A ⊆ 集合 B"型断言必须同时断言 A 非空且大小符合预期；检测器测试必须同时有正例与负例。
- **任何链接 / 路径 / 分块类改动，验收必须跑真实语料**（Task 12）。
- **开源卫生**：不得把真实笔记标题或本机家目录绝对路径写进仓库任何文件；提交前跑 CLAUDE.md
  「开源卫生」节里那条 `git grep` 必须无命中（**本计划刻意不写出那个字面量**——写进来
  就会让那条检查从二元判定退化成每次都要人肉甄别）。
- 常量值（spec 已定）：`COHESION_LIFT_MIN = 0.12`、`TOPIC_INSIGHT_CAP = 12`、`INSUFFICIENT_TOPICS_THRESHOLD = 4`、`RESIDUAL_HIGH_THRESHOLD = 0.70`、`GLOBAL_DF_CAP` 初值 `0.05`、`KEYWORD_TOP_K = 4`、`MIN_CLUSTER_DF = 2`、`MAX_CLUSTER_DF_RATIO = 0.9`、`CJK_PMI_MIN_BIGRAM = 2.0`、`CJK_PMI_MIN_TRIGRAM = 3.0`。
- 稳定枚举：`insights_reason ∈ {no_index, index_failed, contract_violation, naming_failed, io_failed}`。
- 退出码：`0` 成功 / `1` 输出冲突 / `2` 用法错误 / `3` 输入不安全或损坏 / `4` I/O 失败 / `5` 索引未完成 / **`6` 索引完成但洞察未完成**。
- 跑测试：`.venv/bin/python -m pytest -q`

## 文件结构

**新建：**

| 文件 | 唯一职责 | 不认识 |
|---|---|---|
| `src/kb_init/subdivide.py` | 内聚度检测器 + 过大簇二次细分 | 文本、洞察、磁盘 |
| `src/kb_init/stopwords.py` | 内置多语言功能词表（纯数据） | 一切 |
| `src/kb_init/keywords.py` | 混合脚本关键词抽取（纯函数） | 索引结构、洞察、磁盘 |
| `src/kb_init/insights.py` | 三族洞察生成 + `presentation_groups` + 唯一写盘 | 渲染细节 |
| `src/kb_init/insights_md.py` | `insights.md` 的唯一真源：渲染 / 解析 / 校验 | 索引、聚类 |

**修改：**

| 文件 | 改什么 |
|---|---|
| `src/kb_init/cluster.py` | `cluster_documents` 增加 `cluster_selection_method` 与 `group_id_prefix` 两个关键字参数 |
| `src/kb_init/index.py` | `build_analysis()` 抽出、`build_index(extra_analyses=)`、`validate_index` 遍历全部 analyses、新增 `read_index()` |
| `src/kb_init/pipeline.py` | 索引阶段内追加 2A′；新增洞察阶段；`run()` 返回 `insights_status` |
| `src/kb_init/manifest.py` | 新增 `insights_status` / `insights_reason` |
| `src/kb_init/cli.py` | 退出码 6；`kb-init validate <insights.md>` 子命令 |
| `README.md` / `docs/DESIGN.md` / `STATUS.md` / 2A spec | 见 Task 13 |

**测试：** `tests/test_subdivide.py`、`tests/test_keywords.py`、`tests/test_insights.py`、`tests/test_insights_md.py` 新建；`tests/test_cluster.py`、`tests/test_index.py`、`tests/test_index_pipeline.py`、`tests/test_cli.py`、`tests/test_real_corpus.py` 追加。

---

### Task 1: 内聚度检测器

**Files:**
- Create: `src/kb_init/subdivide.py`
- Test: `tests/test_subdivide.py`

**Interfaces:**
- Consumes: 无（纯 numpy）
- Produces:
  - `COHESION_LIFT_MIN: float = 0.12`
  - `cohesion(rows: np.ndarray) -> float`
  - `group_lifts(members_by_group: dict[str, list[str]], residual_ids: list[str], rows: dict[str, np.ndarray]) -> dict[str, float]`
  - `flagged_groups(lifts: dict[str, float], lift_min: float = COHESION_LIFT_MIN) -> list[str]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_subdivide.py
import numpy as np
import pytest

from kb_init.subdivide import COHESION_LIFT_MIN, cohesion, flagged_groups, group_lifts


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _rows(spec):
    """spec: {doc_id: 向量}，一律 L2 归一（与 embed.py 的输出契约一致）"""
    return {k: _unit(v) for k, v in spec.items()}


def test_cohesion_of_identical_vectors_is_one():
    rows = np.vstack([_unit([1.0, 0.0, 0.0])] * 4)
    assert cohesion(rows) == pytest.approx(1.0, abs=1e-6)


def test_cohesion_of_orthogonal_spread_is_lower():
    rows = np.vstack([_unit([1.0, 0.0, 0.0]), _unit([0.0, 1.0, 0.0]),
                      _unit([0.0, 0.0, 1.0])])
    assert cohesion(rows) == pytest.approx(0.5774, abs=1e-3)


def test_cohesion_needs_at_least_two_rows():
    with pytest.raises(ValueError):
        cohesion(np.vstack([_unit([1.0, 0.0, 0.0])]))


def test_lift_separates_tight_group_from_scattered_group():
    # tight：三篇几乎同向。blob：三篇互相正交（与 residual 一样散）
    rows = _rows({
        "t1": [1.0, 0.02, 0.0], "t2": [1.0, 0.0, 0.03], "t3": [0.99, 0.01, 0.01],
        "b1": [1.0, 0.0, 0.0],  "b2": [0.0, 1.0, 0.0],  "b3": [0.0, 0.0, 1.0],
        "r1": [1.0, 0.0, 0.0],  "r2": [0.0, 1.0, 0.0],  "r3": [0.0, 0.0, 1.0],
    })
    lifts = group_lifts({"g01": ["t1", "t2", "t3"], "g02": ["b1", "b2", "b3"]},
                        ["r1", "r2", "r3"], rows)
    assert lifts["g01"] > COHESION_LIFT_MIN          # 正例：紧致簇必须通过
    assert lifts["g02"] < COHESION_LIFT_MIN          # 负例：与基线同散的簇必须被标记
    assert flagged_groups(lifts) == ["g02"]


def test_no_group_is_flagged_when_all_are_tight():
    """负例的负例：检测器不能把所有簇都判为过大——一个恒返回 True 的检测器
    也能让「巨簇被标记」那条测试全绿。"""
    rows = _rows({
        "a1": [1.0, 0.01, 0.0], "a2": [1.0, 0.0, 0.02],
        "b1": [0.0, 1.0, 0.01], "b2": [0.01, 1.0, 0.0],
        "r1": [1.0, 0.0, 0.0],  "r2": [0.0, 1.0, 0.0], "r3": [0.0, 0.0, 1.0],
    })
    lifts = group_lifts({"g01": ["a1", "a2"], "g02": ["b1", "b2"]},
                        ["r1", "r2", "r3"], rows)
    assert flagged_groups(lifts) == []
    assert len(lifts) == 2                            # 防「返回空 dict」让上面恒真


def test_empty_residual_baseline_flags_nothing():
    """residual 为空时没有可比基线。宁可不判，也不要拿 0 当基线把所有簇判为通过。"""
    rows = _rows({"a1": [1.0, 0.0, 0.0], "a2": [0.0, 1.0, 0.0]})
    lifts = group_lifts({"g01": ["a1", "a2"]}, [], rows)
    assert lifts == {}
    assert flagged_groups(lifts) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_subdivide.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.subdivide'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/subdivide.py
"""过大簇的检测与二次细分。只吃向量与 doc_id，**不认识文本**。

「多大算过大」不用篇数比例这种只能在手上这几份语料上调出来的魔数，改用语料
自校准的判据：把簇的内聚度与**本语料 residual 集合**的内聚度相比。residual
按定义就是「没有主题的一堆」，它天然是这份语料的无主题基线。
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

# 实测：六个正常簇落在 +0.18…+0.23，一个 509 篇的大杂烩落在 +0.069，中间是空的。
# 阈值取在空档里——与 2A 给 time_axis 定 0.30 是同一条依据，不是调参结果。
COHESION_LIFT_MIN = 0.12


def cohesion(rows: np.ndarray) -> float:
    """成员向量到其质心的平均余弦。输入必须是已 L2 归一的行向量。"""
    rows = np.asarray(rows, dtype=np.float64)
    if rows.ndim != 2 or rows.shape[0] < 2:
        raise ValueError("内聚度至少需要两行向量")
    centroid = rows.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm == 0:
        return 0.0
    return float((rows @ (centroid / norm)).mean())


def group_lifts(
    members_by_group: Mapping[str, Sequence[str]],
    residual_ids: Sequence[str],
    rows: Mapping[str, np.ndarray],
) -> dict[str, float]:
    """每个 group 的内聚度相对 residual 基线的提升量。

    residual 不足两篇时**返回空字典**：没有基线就不判，而不是拿 0 当基线——
    那会把所有簇都判为「远高于基线」，检测器就永远不会说不。
    """
    baseline_rows = [rows[d] for d in residual_ids if d in rows]
    if len(baseline_rows) < 2:
        return {}
    baseline = cohesion(np.vstack(baseline_rows))
    lifts: dict[str, float] = {}
    for group_id, members in members_by_group.items():
        member_rows = [rows[d] for d in members if d in rows]
        if len(member_rows) < 2:
            continue
        lifts[group_id] = cohesion(np.vstack(member_rows)) - baseline
    return lifts


def flagged_groups(
    lifts: Mapping[str, float], lift_min: float = COHESION_LIFT_MIN
) -> list[str]:
    """内聚度没比「未分类堆」高出多少的 group——它不是一个主题。"""
    return sorted(g for g, lift in lifts.items() if lift < lift_min)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_subdivide.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/subdivide.py tests/test_subdivide.py
git commit -m "feat(2A'): 内聚度检测器——用相对 residual 基线的提升量判过大簇"
```

---

### Task 2: `cluster_documents` 支持 leaf 模式与 group_id 前缀

**Files:**
- Modify: `src/kb_init/cluster.py:61-144`
- Test: `tests/test_cluster.py`（追加）

**Interfaces:**
- Consumes: 现有 `cluster_documents(doc_ids, matrix, *, min_cluster_size=5, min_samples=5)`
- Produces: `cluster_documents(doc_ids, matrix, *, min_cluster_size=5, min_samples=5, cluster_selection_method="eom", group_id_prefix="g") -> tuple[list[Group], list[Assignment]]`
  - 默认值保持现有行为逐字节不变；`group_id_prefix="g01s"` 时产出 `g01s01` / `g01s02`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cluster.py 追加
import numpy as np

from kb_init.cluster import cluster_documents


def _blobs(centres, per_blob=6, jitter=0.01):
    """围绕给定中心生成确定性的小簇，不用随机数——测试不能靠运气。"""
    ids, rows = [], []
    for c_idx, centre in enumerate(centres):
        for k in range(per_blob):
            v = np.array(centre, dtype=np.float32).copy()
            v[c_idx % len(centre)] += jitter * (k + 1)
            v /= np.linalg.norm(v)
            ids.append(f"d{c_idx}{k:02d}")
            rows.append(v)
    return ids, np.vstack(rows)


def test_group_id_prefix_is_applied():
    ids, matrix = _blobs([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    groups, _ = cluster_documents(ids, matrix, group_id_prefix="g01s")
    assert groups, "前缀测试需要至少一个簇，否则断言恒真"
    assert all(g.group_id.startswith("g01s") for g in groups)
    assert len({g.group_id for g in groups}) == len(groups)


def test_default_prefix_and_method_unchanged():
    ids, matrix = _blobs([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    groups, _ = cluster_documents(ids, matrix)
    assert groups and groups[0].group_id == "g01"


def test_leaf_method_is_accepted_and_deterministic():
    ids, matrix = _blobs([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    first = cluster_documents(ids, matrix, cluster_selection_method="leaf")
    second = cluster_documents(ids, matrix, cluster_selection_method="leaf")
    assert [g.group_id for g in first[0]] == [g.group_id for g in second[0]]
    assert [(a.doc_id, a.disposition) for a in first[1]] == \
           [(a.doc_id, a.disposition) for a in second[1]]
    assert len(first[0]) >= 2, "确定性断言需要真的聚出簇，否则两边都空也相等"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cluster.py -q`
Expected: FAIL — `TypeError: cluster_documents() got an unexpected keyword argument 'group_id_prefix'`

- [ ] **Step 3: 最小实现**

在 `src/kb_init/cluster.py` 里把签名与两处用到的地方改掉：

```python
def cluster_documents(
    doc_ids: Sequence[str],
    matrix: np.ndarray,
    *,
    min_cluster_size: int = 5,
    min_samples: int = 5,
    cluster_selection_method: str = "eom",
    group_id_prefix: str = "g",
) -> tuple[list[Group], list[Assignment]]:
```

`HDBSCAN(...)` 调用处加一个参数：

```python
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method=cluster_selection_method,
        copy=True,
    )
```

group_id 生成处换成前缀：

```python
    for i, members in enumerate(ordered, start=1):
        group_id = f"{group_id_prefix}{i:02d}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_cluster.py -q && .venv/bin/python -m pytest -q`
Expected: 全部通过（默认参数不变，既有测试不应有任何回归）

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/cluster.py tests/test_cluster.py
git commit -m "feat(2A'): cluster_documents 支持 leaf 模式与 group_id 前缀"
```

---

### Task 3: 二次细分编排

**Files:**
- Modify: `src/kb_init/subdivide.py`
- Test: `tests/test_subdivide.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `group_lifts` / `flagged_groups` / `COHESION_LIFT_MIN`；Task 2 的 `cluster_documents`
- Produces: `subdivide_group(group_id, member_ids, rows, baseline_cohesion, *, min_cluster_size=5, min_samples=5, lift_min=COHESION_LIFT_MIN) -> tuple[list[Group], list[Assignment]]`
  - 返回的 assignments **恰好覆盖 `member_ids` 全体**；未进入通过子簇的成员 `disposition="residual"`，`reason_code ∈ {"subdivision_rejected", "under_differentiated_parent"}`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_subdivide.py 追加
import numpy as np

from kb_init.subdivide import cohesion, subdivide_group


def _two_tight_blobs(n=6):
    rows, ids = {}, []
    for i in range(n):
        for axis, tag in ((0, "a"), (1, "b")):
            v = np.zeros(3, dtype=np.float32)
            v[axis] = 1.0
            v[2] = 0.001 * i
            v /= np.linalg.norm(v)
            doc = f"{tag}{i:02d}"
            rows[doc] = v
            ids.append(doc)
    return ids, rows


def test_subdivision_splits_a_blob_into_passing_children():
    ids, rows = _two_tight_blobs()
    scattered = np.vstack([rows[d] for d in ids])
    baseline = 0.3                                   # 远低于两个团各自的内聚度
    groups, assignments = subdivide_group("g01", ids, rows, baseline,
                                          min_cluster_size=3, min_samples=3)
    assert len(groups) >= 2, "只产出一个子簇时下面的断言会恒真"
    assert all(g.group_id.startswith("g01s") for g in groups)
    # 覆盖性：恰好覆盖父簇成员，不多不少
    assert sorted(a.doc_id for a in assignments) == sorted(ids)


def test_children_failing_the_detector_fold_back_to_residual():
    ids, rows = _two_tight_blobs()
    baseline = 0.999                                 # 高到没有子簇能通过
    groups, assignments = subdivide_group("g01", ids, rows, baseline,
                                          min_cluster_size=3, min_samples=3)
    assert groups == []
    assert len(assignments) == len(ids)              # 防「返回空列表」让下面恒真
    assert all(a.disposition == "residual" for a in assignments)
    assert {a.reason_code for a in assignments} <= {
        "subdivision_rejected", "under_differentiated_parent"}


def test_assignments_never_reference_a_dropped_child_group():
    ids, rows = _two_tight_blobs()
    groups, assignments = subdivide_group("g01", ids, rows, 0.3,
                                          min_cluster_size=3, min_samples=3)
    known = {g.group_id for g in groups}
    referenced = {m.group_id for a in assignments for m in a.memberships}
    assert referenced, "没有任何 membership 时这条断言恒真"
    assert referenced <= known


def test_member_counts_match_actual_memberships():
    ids, rows = _two_tight_blobs()
    groups, assignments = subdivide_group("g01", ids, rows, 0.3,
                                          min_cluster_size=3, min_samples=3)
    for g in groups:
        actual = sum(1 for a in assignments
                     for m in a.memberships if m.group_id == g.group_id)
        assert actual > 0
        assert g.member_counts["total_docs"] == actual
        assert g.member_counts["core"] == actual
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_subdivide.py -q`
Expected: FAIL — `ImportError: cannot import name 'subdivide_group'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/subdivide.py 追加
def subdivide_group(
    group_id: str,
    member_ids: Sequence[str],
    rows: Mapping[str, np.ndarray],
    baseline_cohesion: float,
    *,
    min_cluster_size: int = 5,
    min_samples: int = 5,
    lift_min: float = COHESION_LIFT_MIN,
) -> tuple[list, list]:
    """把一个被标记的 group 细分，**子簇逐个过同一个检测器**。

    通不过的子簇不是「勉强留着」——它的成员折回 residual。放行一个通不过的
    子簇，等于用一个更小的大杂烩换掉一个更大的，产物照样在撒谎。

    返回的 assignments 恰好覆盖 `member_ids` 全体：这一层是 analyses[1]，
    它的 input_scope 就是父 group 的成员集合，不多不少。
    """
    from kb_init.cluster import Assignment, cluster_documents

    member_ids = sorted(member_ids)
    matrix = np.vstack([rows[d] for d in member_ids])
    children, child_assignments = cluster_documents(
        member_ids,
        matrix,
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method="leaf",
        group_id_prefix=f"{group_id}s",
    )

    members_of: dict[str, list[str]] = {}
    for a in child_assignments:
        for m in a.memberships:
            members_of.setdefault(m.group_id, []).append(a.doc_id)

    kept_children = []
    for child in children:
        members = members_of.get(child.group_id, [])
        if len(members) < 2:
            continue
        lift = cohesion(np.vstack([rows[d] for d in members])) - baseline_cohesion
        if lift >= lift_min:
            kept_children.append(child)
    kept_ids = {c.group_id for c in kept_children}

    assignments = []
    for a in child_assignments:
        keep = [m for m in a.memberships if m.group_id in kept_ids]
        if keep:
            assignments.append(Assignment(a.doc_id, "assigned", tuple(keep), None))
        elif a.memberships:
            assignments.append(
                Assignment(a.doc_id, "residual", (), "subdivision_rejected")
            )
        else:
            assignments.append(
                Assignment(a.doc_id, "residual", (), "under_differentiated_parent")
            )
    return kept_children, assignments
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_subdivide.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/subdivide.py tests/test_subdivide.py
git commit -m "feat(2A'): 二次细分编排——子簇逐个过同一检测器，不过的折回 residual"
```

---

### Task 4: `index.py` 支持多 analysis

**Files:**
- Modify: `src/kb_init/index.py:75-133`（`build_index`）、`:140-244`（`validate_index`）
- Test: `tests/test_index.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 Group / Assignment
- Produces:
  - `build_analysis(*, analysis_id, parent_analysis_id, input_scope, groups, assignments, method, time_axis) -> dict`
  - `build_index(..., extra_analyses: Sequence[dict] = ()) -> dict`（其余签名不变）
  - `validate_index` 遍历全部 analyses；子分析额外校验：`input_scope` 指向的父 group 存在、子分析的 doc_id 集合**恰好等于**父 group 成员集合

- [ ] **Step 1: 写失败测试**

```python
# tests/test_index.py 追加
import pytest

from kb_init.cluster import Assignment, Group, Membership
from kb_init.index import build_analysis, build_index, validate_index


def _method():
    return {"family": "density", "name": "hdbscan", "model": "fake",
            "model_revision": "", "params": {"min_cluster_size": 3},
            "seed": 0, "splitter": {"name": "injected", "max_tokens": 512,
                                    "fallback_used": False},
            "pooling": "mean_l2", "score_kind": "density_membership",
            "score_direction": "higher_better", "decision_threshold": None}


def _time_axis():
    return {"dated_docs": 0, "total_docs": 3, "coverage": 0.0,
            "threshold": 0.30, "available": False, "per_group": None}


def _parent():
    groups = [Group("g01", "semantic_topic",
                    {"core": 2, "halo": 0, "micro": 0, "total_docs": 2},
                    [{"doc_id": "d1", "kind": "medoid"}])]
    assignments = [
        Assignment("d1", "assigned", (Membership("g01", "core", 1.0),), None),
        Assignment("d2", "assigned", (Membership("g01", "core", 1.0),), None),
        Assignment("d3", "residual", (), "low_local_density"),
    ]
    return groups, assignments


def _child():
    groups = [Group("g01s01", "semantic_topic",
                    {"core": 2, "halo": 0, "micro": 0, "total_docs": 2},
                    [{"doc_id": "d1", "kind": "medoid"}])]
    assignments = [
        Assignment("d1", "assigned", (Membership("g01s01", "core", 1.0),), None),
        Assignment("d2", "assigned", (Membership("g01s01", "core", 1.0),), None),
    ]
    return groups, assignments


def _index_with_child(child_assignments=None):
    pg, pa = _parent()
    cg, ca = _child()
    child = build_analysis(
        analysis_id="topics-02", parent_analysis_id="topics-01",
        input_scope={"kind": "parent_group", "analysis_id": "topics-01",
                     "group_id": "g01"},
        groups=cg, assignments=child_assignments or ca,
        method=_method(), time_axis=_time_axis())
    return build_index(
        run_id="r", corpus_hash="c", chunks=[], groups=pg, assignments=pa,
        method=_method(), time_axis=_time_axis(), versions={},
        vector_doc_ids=[], extra_analyses=[child])


def test_extra_analysis_is_appended_and_validates():
    index = _index_with_child()
    assert len(index["analyses"]) == 2
    assert index["analyses"][1]["analysis_id"] == "topics-02"
    assert index["analyses"][1]["parent_analysis_id"] == "topics-01"
    validate_index(index, ["d1", "d2", "d3"])


def test_parent_analysis_is_untouched_by_the_child():
    index = _index_with_child()
    parent = index["analyses"][0]
    assert parent["coverage"] == {"assigned": 2, "ambiguous": 0, "residual": 1}
    assert [a["doc_id"] for a in parent["assignments"]] == ["d1", "d2", "d3"]


def test_child_must_cover_exactly_the_parent_group_members():
    cg, ca = _child()
    index = _index_with_child(child_assignments=ca[:1])       # 少了 d2
    with pytest.raises(ValueError, match="父 group"):
        validate_index(index, ["d1", "d2", "d3"])


def test_child_referencing_unknown_parent_group_is_rejected():
    pg, pa = _parent()
    cg, ca = _child()
    child = build_analysis(
        analysis_id="topics-02", parent_analysis_id="topics-01",
        input_scope={"kind": "parent_group", "analysis_id": "topics-01",
                     "group_id": "g99"},
        groups=cg, assignments=ca, method=_method(), time_axis=_time_axis())
    index = build_index(run_id="r", corpus_hash="c", chunks=[], groups=pg,
                        assignments=pa, method=_method(), time_axis=_time_axis(),
                        versions={}, vector_doc_ids=[], extra_analyses=[child])
    with pytest.raises(ValueError, match="不存在"):
        validate_index(index, ["d1", "d2", "d3"])


def test_analysis_ids_must_be_unique():
    pg, pa = _parent()
    cg, ca = _child()
    dup = build_analysis(
        analysis_id="topics-01", parent_analysis_id="topics-01",
        input_scope={"kind": "parent_group", "analysis_id": "topics-01",
                     "group_id": "g01"},
        groups=cg, assignments=ca, method=_method(), time_axis=_time_axis())
    index = build_index(run_id="r", corpus_hash="c", chunks=[], groups=pg,
                        assignments=pa, method=_method(), time_axis=_time_axis(),
                        versions={}, vector_doc_ids=[], extra_analyses=[dup])
    with pytest.raises(ValueError, match="analysis_id"):
        validate_index(index, ["d1", "d2", "d3"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_index.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_analysis'`

- [ ] **Step 3: 最小实现**

在 `src/kb_init/index.py` 抽出 `build_analysis`，让 `build_index` 复用它并接受 `extra_analyses`：

```python
def build_analysis(
    *,
    analysis_id: str,
    parent_analysis_id: str | None,
    input_scope: dict,
    groups: Sequence[Group],
    assignments: Sequence[Assignment],
    method: dict,
    time_axis: dict,
) -> dict:
    dispositions = [a.disposition for a in assignments]
    return {
        "analysis_id": analysis_id,
        "parent_analysis_id": parent_analysis_id,
        "input_scope": input_scope,
        "method": method,
        "groups": [
            {
                "group_id": g.group_id,
                "kind": g.kind,
                "member_counts": g.member_counts,
                "representatives": g.representatives,
                "prototype": g.prototype,
            }
            for g in groups
        ],
        "assignments": [
            {
                "doc_id": a.doc_id,
                "disposition": a.disposition,
                "memberships": [asdict(m) for m in a.memberships],
                "reason_code": a.reason_code,
            }
            for a in assignments
        ],
        "coverage": {
            "assigned": dispositions.count("assigned"),
            "ambiguous": dispositions.count("ambiguous"),
            "residual": dispositions.count("residual"),
        },
        "time_axis": time_axis,
    }
```

`build_index` 的 `analyses` 改成：

```python
        "analyses": [
            build_analysis(
                analysis_id=ANALYSIS_ID,
                parent_analysis_id=None,
                input_scope={"kind": "all_kept_docs"},
                groups=groups,
                assignments=assignments,
                method=method,
                time_axis=time_axis,
            ),
            *extra_analyses,
        ],
```

并在签名末尾加 `extra_analyses: Sequence[dict] = ()`。

`validate_index` 改为：把原来针对 `index["analyses"][0]` 的整段校验抽成
`_validate_analysis(analysis, expected_doc_ids)`，然后：

```python
    analyses = index["analyses"]
    ids = [a["analysis_id"] for a in analyses]
    if len(set(ids)) != len(ids):
        raise ValueError("analysis_id 重复")

    root = analyses[0]
    _validate_analysis(root, sorted(kept_doc_ids))

    members_by_group: dict[tuple[str, str], set[str]] = {}
    for a in analyses:
        for asg in a["assignments"]:
            for m in asg["memberships"]:
                members_by_group.setdefault(
                    (a["analysis_id"], m["group_id"]), set()
                ).add(asg["doc_id"])

    for child in analyses[1:]:
        scope = child["input_scope"]
        if scope.get("kind") != "parent_group":
            raise ValueError(f"子分析的 input_scope 必须是 parent_group：{scope}")
        key = (scope["analysis_id"], scope["group_id"])
        if key not in members_by_group:
            raise ValueError(f"子分析指向不存在的父 group：{key}")
        # 恰好覆盖：多一篇少一篇都会让「呈现级 group」的派生算错，而算错没有症状
        expected = sorted(members_by_group[key])
        actual = sorted(a["doc_id"] for a in child["assignments"])
        if actual != expected:
            raise ValueError(
                f"子分析 {child['analysis_id']} 未恰好覆盖父 group {key} 的成员"
            )
        _validate_analysis(child, expected)
```

注意 `_validate_analysis` 里原有的 chunk / vector 校验属于**索引级**而非分析级，
保留在 `validate_index` 主体里，不要搬进去。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_index.py -q && .venv/bin/python -m pytest -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/index.py tests/test_index.py
git commit -m "feat(2A'): index 支持 analyses 数组——子分析必须恰好覆盖父 group 成员"
```

---

### Task 5: `read_index()` 公共读取器

**Files:**
- Modify: `src/kb_init/index.py`
- Test: `tests/test_index.py`（追加）

**Interfaces:**
- Produces: `read_index(out_dir: Path) -> tuple[dict, np.ndarray]`
  - 校验 `.npy` 的 `ndim==2` / `dtype==float32` / 无 NaN·Inf / `shape[0] == len(vector_doc_ids)`；任一不符抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_index.py 追加
import numpy as np
import pytest

from kb_init.index import read_index, write_index


def _minimal_index():
    return build_index(run_id="r", corpus_hash="c", chunks=[], groups=[],
                       assignments=[], method=_method(), time_axis=_time_axis(),
                       versions={}, vector_doc_ids=["d1", "d2"])


def test_read_index_round_trips(tmp_path):
    index = _minimal_index()
    matrix = np.eye(2, 3, dtype=np.float32)
    write_index(tmp_path, index, matrix)
    got_index, got_matrix = read_index(tmp_path)
    assert got_index["run_id"] == "r"
    assert got_matrix.shape == (2, 3)
    assert got_matrix.dtype == np.float32


def test_read_index_rejects_row_count_mismatch(tmp_path):
    index = _minimal_index()
    write_index(tmp_path, index, np.eye(2, 3, dtype=np.float32))
    np.save(tmp_path / "index-vectors.npy", np.eye(5, 3, dtype=np.float32))
    with pytest.raises(ValueError, match="行数"):
        read_index(tmp_path)


def test_read_index_rejects_non_finite(tmp_path):
    index = _minimal_index()
    write_index(tmp_path, index, np.eye(2, 3, dtype=np.float32))
    bad = np.eye(2, 3, dtype=np.float32)
    bad[0, 0] = np.nan
    np.save(tmp_path / "index-vectors.npy", bad)
    with pytest.raises(ValueError, match="NaN"):
        read_index(tmp_path)


def test_read_index_rejects_wrong_dtype(tmp_path):
    index = _minimal_index()
    write_index(tmp_path, index, np.eye(2, 3, dtype=np.float32))
    np.save(tmp_path / "index-vectors.npy", np.eye(2, 3, dtype=np.float64))
    with pytest.raises(ValueError, match="float32"):
        read_index(tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_index.py -q -k read_index`
Expected: FAIL — `ImportError: cannot import name 'read_index'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/index.py 追加
def read_index(out_dir: Path) -> tuple[dict, "np.ndarray"]:
    """下游（2B/2C/2D/2E）读取索引的**唯一**入口。

    文件被截断时 shape 仍可能「看起来合理」，只比对元数据不够——所以这里把
    2A spec §6 要求读取方做的完整性校验一次性做掉，避免三个下游各写一遍、
    各漏一条。
    """
    out_dir = Path(out_dir)
    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    matrix = np.load(out_dir / "index-vectors.npy")
    if matrix.ndim != 2:
        raise ValueError(f"向量矩阵必须是二维，得到 {matrix.ndim} 维")
    if matrix.dtype != np.float32:
        raise ValueError(f"向量矩阵必须是 float32，得到 {matrix.dtype}")
    if matrix.size and not np.all(np.isfinite(matrix)):
        raise ValueError("向量矩阵含 NaN 或 Inf")
    expected = len(index["vector_doc_ids"])
    if matrix.shape[0] != expected:
        raise ValueError(f"向量行数 {matrix.shape[0]} 与 vector_doc_ids {expected} 不符")
    return index, matrix
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_index.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/index.py tests/test_index.py
git commit -m "feat: read_index 公共读取器——把 .npy 完整性校验收在一处"
```

---

### Task 6: 2A′ 接进索引阶段

**Files:**
- Modify: `src/kb_init/pipeline.py:99-227`（`_run_index_stage`）
- Test: `tests/test_index_pipeline.py`（追加）

**Interfaces:**
- Consumes: Task 1/3 的 `group_lifts` / `flagged_groups` / `subdivide_group` / `cohesion`；Task 4 的 `build_analysis` / `build_index(extra_analyses=)`
- Produces: `_run_index_stage` 在写盘前追加 `analyses[1..]`；细分失败即索引失败（回滚整个索引子事务）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_index_pipeline.py 追加
import json

from kb_init.pipeline import run
from tests.fakes import FakeEmbedder


def _corpus(tmp_path, blobs):
    """blobs: [(前缀, 篇数, 正文模板)]。同前缀的正文高度相似 → fake 向量也相似。"""
    src = tmp_path / "src"
    src.mkdir()
    for prefix, count, body in blobs:
        for i in range(count):
            (src / f"{prefix}-{i:02d}.md").write_text(
                f"# {prefix} {i}\n\n{body}\n" + ("内容 " * 40), encoding="utf-8")
    return src


def test_subdivision_appends_a_second_analysis_when_a_group_is_flagged(tmp_path):
    """构造一份让 fake 向量聚成「一个松散大簇」的语料，断言它被细分。

    注意：fake 向量由文本 SHA-256 派生，与文本语义无关——本测试验证的是
    **管线接线**，语义质量由 Task 12 的真实语料验收负责。
    """
    src = _corpus(tmp_path, [("alpha", 12, "aaa"), ("beta", 12, "bbb")])
    out = tmp_path / "out"
    run(src, out, embedder=FakeEmbedder(), run_id="t")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert len(index["analyses"]) >= 1
    for child in index["analyses"][1:]:
        assert child["parent_analysis_id"] == "topics-01"
        assert child["input_scope"]["kind"] == "parent_group"


def test_parent_analysis_bytes_are_unaffected_by_subdivision(tmp_path):
    src = _corpus(tmp_path, [("alpha", 12, "aaa")])
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    run(src, out_a, embedder=FakeEmbedder(), run_id="t")
    run(src, out_b, embedder=FakeEmbedder(), run_id="t")
    a = json.loads((out_a / "index.json").read_text(encoding="utf-8"))
    b = json.loads((out_b / "index.json").read_text(encoding="utf-8"))
    assert a["analyses"][0] == b["analyses"][0]
    assert a == b                                    # 确定性：整份索引逐字段相同


def test_subdivision_failure_rolls_back_the_whole_index(tmp_path, monkeypatch):
    import kb_init.subdivide as sd

    monkeypatch.setattr(sd, "subdivide_group",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸")))
    monkeypatch.setattr(sd, "flagged_groups", lambda *a, **k: ["g01"])
    src = _corpus(tmp_path, [("alpha", 12, "aaa")])
    out = tmp_path / "out"
    summary = run(src, out, embedder=FakeEmbedder(), run_id="t")
    assert summary["index_status"] == "failed"
    assert not (out / "index.json").exists()
    assert not (out / "index-vectors.npy").exists()
    assert (out / "knowledge").is_dir()              # 清洗产物必须还在
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_index_pipeline.py -q`
Expected: FAIL — 第一条断言 `child["parent_analysis_id"]` 无从谈起（只有一个 analysis 且没有细分逻辑）；第三条 `index_status` 为 `complete`

- [ ] **Step 3: 最小实现**

在 `_run_index_stage` 里，`build_index(...)` **之前**插入细分段（注意 import 写在 try 内部，
沿用该函数既有的纪律）：

```python
        from kb_init.subdivide import (
            cohesion,
            flagged_groups,
            group_lifts,
            subdivide_group,
        )
        from kb_init.index import build_analysis

        row_of = {d: matrix[i] for i, d in enumerate(doc_ids)}
        members_by_group: dict[str, list[str]] = {}
        for a in assignments:
            for m in a.memberships:
                members_by_group.setdefault(m.group_id, []).append(a.doc_id)
        residual_ids = [a.doc_id for a in assignments if a.disposition == "residual"]

        extra_analyses = []
        lifts = group_lifts(members_by_group, residual_ids, row_of)
        flagged = flagged_groups(lifts)
        if flagged:
            baseline_rows = [row_of[d] for d in residual_ids if d in row_of]
            baseline = cohesion(np.vstack(baseline_rows))
            for n, gid in enumerate(flagged, start=2):
                child_groups, child_assignments = subdivide_group(
                    gid, members_by_group[gid], row_of, baseline,
                    min_cluster_size=5, min_samples=5,
                )
                child_method = dict(method_dict)
                child_method["params"] = {
                    **method_dict["params"],
                    "cluster_selection_method": "leaf",
                    "cohesion_lift_min": COHESION_LIFT_MIN,
                }
                extra_analyses.append(build_analysis(
                    analysis_id=f"topics-{n:02d}",
                    parent_analysis_id="topics-01",
                    input_scope={"kind": "parent_group",
                                 "analysis_id": "topics-01", "group_id": gid},
                    groups=child_groups,
                    assignments=child_assignments,
                    method=child_method,
                    time_axis=build_time_axis(0, len(members_by_group[gid])),
                ))
```

把现有那个内联的 `method={...}` 字典先提到变量 `method_dict`，父分析与子分析共用它的
基础字段；父分析的 `params` 额外记 `"cluster_selection_method": "eom"` 与
`"cohesion_lift_min": COHESION_LIFT_MIN`——**参数不落盘等于产物隐瞒了自己是怎么来的**。

`build_index(...)` 调用加上 `extra_analyses=extra_analyses`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/pipeline.py tests/test_index_pipeline.py
git commit -m "feat(2A'): 细分接进索引阶段——失败回滚整个索引子事务"
```

---

### Task 7: 内置功能词表

**Files:**
- Create: `src/kb_init/stopwords.py`
- Test: `tests/test_keywords.py`（新建，先只测词表）

**Interfaces:**
- Produces: `FUNCTION_WORDS: frozenset[str]`（小写拉丁功能词）、`CJK_GLUE: frozenset[str]`（单字）、`STOPLIST_VERSION: str = "bundled-v1"`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keywords.py
from kb_init.stopwords import CJK_GLUE, FUNCTION_WORDS, STOPLIST_VERSION


def test_covers_the_function_words_seen_in_real_corpora():
    """实测中真的把这些词选成过簇名——它们必须在表里。"""
    for w in ("che", "non", "una", "per", "essere",
              "the", "that", "which", "there", "more", "they",
              "can", "like", "about", "world"):
        assert w in FUNCTION_WORDS, w


def test_does_not_swallow_real_topic_words():
    """表不能宽到把真主题词吃掉——否则名字会全空。"""
    for w in ("grammatica", "design", "backend", "notification", "feedback"):
        assert w not in FUNCTION_WORDS, w


def test_cjk_glue_is_single_characters_only():
    assert CJK_GLUE
    assert all(len(c) == 1 for c in CJK_GLUE)
    for c in ("的", "了", "是", "在", "我", "们", "这", "和", "就", "有"):
        assert c in CJK_GLUE, c


def test_stoplist_version_is_recorded():
    assert STOPLIST_VERSION == "bundled-v1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_keywords.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.stopwords'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/stopwords.py
"""内置功能词表。

**这张表按定义覆盖不了没收录的语言**——单一语言独占一个簇时，该语言的功能词
会被判为区分性关键词。这是已知失效模式（spec §4.4），产品层的兜底是「关键词
永远与证据标题同时呈现 + 人肉 gate 可取消勾选 + L3 可重命名」，不是把这张表
无限加长。加语言之前先问：这门语言的簇真的出现过吗？
"""
from __future__ import annotations

STOPLIST_VERSION = "bundled-v1"

_EN = """a about above after again against all also am an and any are as at be
because been before being below between both but by can cannot could did do does
doing down during each few for from further had has have having he her here hers
him his how i if in into is it its just like me more most my no nor not now of
off on once only or other our out over own same she should so some such than that
the their them then there these they this those through to too under until up
very was we were what when where which while who whom why will with would you
your world things thing get got make made take taken"""

_IT = """a ad agli ai al alla alle allo anche c che chi ci co coi col come con
contro cui da dagli dai dal dalla dalle dallo degli dei del della delle dello di
dov dove e ed essere fa fare gli ha hai hanno ho i il in io la le lo loro ma me
mi ne negli nei nel nella nelle nello no noi non o per perche piu quale quando
quel quella quelle quello questa queste questi questo sara se sei si sia siamo
sono su sugli sui sul sulla sulle suo sua tra tu tuo un una uno vi voi"""

FUNCTION_WORDS = frozenset(_EN.split()) | frozenset(_IT.split())

# 中文没有词边界，n-gram 会切出「是周」「们这」这类非词。这些黏着字单独出现
# 在 n-gram 里通常意味着切错了，而不是命中了一个词。
CJK_GLUE = frozenset(
    "的了是在我们这那和就有也都要会对上下不与及其之为以于把被让给从向"
    "很非常还再又才只把使得所因所以但如果虽然"
)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_keywords.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/stopwords.py tests/test_keywords.py
git commit -m "feat: 内置多语言功能词表（bundled-v1）"
```

---

### Task 8: 关键词抽取

**Files:**
- Create: `src/kb_init/keywords.py`
- Test: `tests/test_keywords.py`（追加）

**Interfaces:**
- Consumes: Task 7 的 `FUNCTION_WORDS` / `CJK_GLUE` / `STOPLIST_VERSION`
- Produces:
  - `DEFAULT_PARAMS: dict`（含 spec 定的全部常量 + `stoplist`）
  - `extract_keywords(bodies: Mapping[str, str], groups: Mapping[str, Sequence[str]], *, top_k: int = 4, params: Mapping | None = None) -> dict[str, list[str]]`
  - `strip_markdown(text: str) -> str`
  - `tokenize(text: str) -> list[str]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keywords.py 追加
from kb_init.keywords import DEFAULT_PARAMS, extract_keywords, strip_markdown, tokenize


def test_strip_markdown_removes_link_targets_images_urls_and_code():
    text = ("![图](assets/a.png) 见 [文档](https://example.com/doc) 与 "
            "`code_token` 还有 https://example.com/bare")
    out = strip_markdown(text)
    assert "assets" not in out and "example.com" not in out
    assert "code_token" not in out
    assert "文档" in out                     # 链接文字要保留，只去目标


def test_tokenize_splits_latin_words_and_cjk_ngrams():
    toks = tokenize("hello 设计方法 world")
    assert "hello" in toks and "world" in toks
    assert "设计" in toks and "设计方" in toks
    assert "h" not in toks                    # 单字符拉丁不成词


def test_function_words_never_become_keywords():
    bodies = {f"d{i}": "che non una per essere grammatica preposizione " * 5
              for i in range(6)}
    bodies.update({f"o{i}": "backend api database " * 5 for i in range(6)})
    got = extract_keywords(bodies, {"g01": [f"d{i}" for i in range(6)]})
    assert got["g01"], "关键词为空会让下面的断言恒真"
    assert len(got["g01"]) == 4
    assert not ({"che", "non", "una", "per", "essere"} & set(got["g01"]))
    assert "grammatica" in got["g01"] or "preposizione" in got["g01"]


def test_cjk_shift_fragments_are_filtered():
    bodies = {f"d{i}": "我们这周的上课时间安排 设计推敲造型 " * 6 for i in range(6)}
    bodies.update({f"o{i}": "backend api " * 6 for i in range(6)})
    got = extract_keywords(bodies, {"g01": [f"d{i}" for i in range(6)]})
    assert got["g01"]
    for junk in ("们这", "是周", "间的", "我们这"):
        assert junk not in got["g01"], junk


def test_overlapping_ngrams_are_deduped():
    bodies = {f"d{i}": "机器学习模型训练 " * 8 for i in range(6)}
    bodies.update({f"o{i}": "unrelated english text " * 8 for i in range(6)})
    got = extract_keywords(bodies, {"g01": [f"d{i}" for i in range(6)]})
    for a in got["g01"]:
        for b in got["g01"]:
            if a != b:
                assert a not in b and b not in a


def test_is_deterministic():
    bodies = {f"d{i}": f"design pioneers modern {i} " * 6 for i in range(6)}
    bodies.update({f"o{i}": "backend api " * 6 for i in range(6)})
    groups = {"g01": [f"d{i}" for i in range(6)]}
    assert extract_keywords(bodies, groups) == extract_keywords(bodies, groups)


def test_empty_and_tiny_groups_do_not_raise():
    bodies = {"d0": "design", "d1": ""}
    got = extract_keywords(bodies, {"g01": ["d1"], "g02": []})
    assert got == {"g01": [], "g02": []}


def test_params_are_exposed_for_recording():
    for key in ("global_df_cap", "min_cluster_df", "max_cluster_df_ratio",
                "cjk_pmi_min_bigram", "cjk_pmi_min_trigram", "stoplist"):
        assert key in DEFAULT_PARAMS
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_keywords.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.keywords'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/keywords.py
"""簇的无监督命名：混合脚本 c-TF-IDF。

**IDF 必须在真实文档层面算，不能在「每簇拼成一篇」的类文档之间算。** 早期原型
犯过这个错：整簇的停用词因为「只有这一簇是意大利语」而显得极其独特，直接成了簇名。

产出的是**关键词**，不是主题名。渲染层的措辞必须是「这些篇里最具区分度的词是…」，
不能写成「你的主题是…」——那是产物在撒谎。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Mapping, Sequence

from kb_init.stopwords import CJK_GLUE, FUNCTION_WORDS, STOPLIST_VERSION

DEFAULT_PARAMS = {
    "method": "ctfidf_multiscript",
    "global_df_cap": 0.05,
    "min_cluster_df": 2,
    "max_cluster_df_ratio": 0.9,
    "cjk_pmi_min_bigram": 2.0,
    "cjk_pmi_min_trigram": 3.0,
    "stoplist": STOPLIST_VERSION,
}

_CJK = r"一-鿿㐀-䶿"
_LATIN = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]{2,}")
_CJK_RUN = re.compile(f"[{_CJK}]+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CODE = re.compile(r"```.*?```|`[^`]*`", re.S)


def strip_markdown(text: str) -> str:
    text = _CODE.sub(" ", text)
    text = _IMG.sub(" ", text)
    text = _LINK.sub(r"\1", text)        # 保留链接文字，去掉目标
    return _URL.sub(" ", text)


def tokenize(text: str) -> list[str]:
    text = strip_markdown(text)
    out = [w.lower() for w in _LATIN.findall(text)]
    for run in _CJK_RUN.findall(text):
        out += [run[i:i + 2] for i in range(len(run) - 1)]
        out += [run[i:i + 3] for i in range(len(run) - 2)]
    return out


def _is_cjk(term: str) -> bool:
    return bool(_CJK_RUN.fullmatch(term))


def _cohesive(term: str, char_freq: Counter, char_total: int,
              term_freq: int, term_total: int, params: Mapping) -> bool:
    """CJK n-gram 的内聚度（PMI）。滑窗会切出「是周」这类非词，它们的出现频率
    可以完全由各字符独立出现解释——PMI 因此接近零。"""
    if not _is_cjk(term):
        return True
    if any(c in CJK_GLUE for c in term):
        return False
    p_term = term_freq / max(term_total, 1)
    p_parts = 1.0
    for c in term:
        p_parts *= char_freq[c] / max(char_total, 1)
    if p_parts <= 0 or p_term <= 0:
        return False
    threshold = (params["cjk_pmi_min_bigram"] if len(term) == 2
                 else params["cjk_pmi_min_trigram"])
    return math.log(p_term / p_parts) > threshold


def _dedupe_overlaps(candidates: Sequence[str], top_k: int) -> list[str]:
    picked: list[str] = []
    for term in candidates:
        if any(term in kept or kept in term for kept in picked):
            continue
        if any(len(term) > 1 and len(kept) > 1
               and (term[:-1] == kept[1:] or term[1:] == kept[:-1])
               for kept in picked):
            continue
        picked.append(term)
        if len(picked) == top_k:
            break
    return picked


def extract_keywords(
    bodies: Mapping[str, str],
    groups: Mapping[str, Sequence[str]],
    *,
    top_k: int = 4,
    params: Mapping | None = None,
) -> dict[str, list[str]]:
    params = {**DEFAULT_PARAMS, **(params or {})}
    tokens = {doc_id: tokenize(text) for doc_id, text in bodies.items()}
    total_docs = len(tokens) or 1

    doc_freq: Counter = Counter()
    for toks in tokens.values():
        doc_freq.update(set(toks))

    char_freq: Counter = Counter()
    for text in bodies.values():
        for run in _CJK_RUN.findall(strip_markdown(text)):
            char_freq.update(run)
    char_total = sum(char_freq.values())

    result: dict[str, list[str]] = {}
    for group_id, member_ids in groups.items():
        members = [d for d in member_ids if d in tokens]
        term_freq: Counter = Counter()
        cluster_df: Counter = Counter()
        for d in members:
            term_freq.update(tokens[d])
            cluster_df.update(set(tokens[d]))
        term_total = sum(term_freq.values())
        if not term_total:
            result[group_id] = []
            continue

        scored: dict[str, float] = {}
        for term, freq in term_freq.items():
            if len(term) < 2 or term in FUNCTION_WORDS:
                continue
            if cluster_df[term] < params["min_cluster_df"]:
                continue
            if len(members) >= 5 and cluster_df[term] / len(members) >= params["max_cluster_df_ratio"]:
                continue
            if doc_freq[term] / total_docs > params["global_df_cap"]:
                continue
            if not _cohesive(term, char_freq, char_total, freq, term_total, params):
                continue
            scored[term] = (freq / term_total) * math.log(1 + total_docs / doc_freq[term])

        # 分数相等时按词本身排序破平——否则同输入两次跑可能给出不同的名字
        ordered = [t for t, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))]
        result[group_id] = _dedupe_overlaps(ordered, top_k)
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_keywords.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/keywords.py tests/test_keywords.py
git commit -m "feat: 混合脚本 c-TF-IDF 关键词抽取（IDF 算在真实文档层面）"
```

---

### Task 9: 呈现级派生 + corpus 族洞察

**Files:**
- Create: `src/kb_init/insights.py`
- Test: `tests/test_insights.py`

**Interfaces:**
- Consumes: Task 4/5 的 index 结构
- Produces:
  - `GroupRef = tuple[str, str]`（`(analysis_id, group_id)`）
  - `presentation_groups(index: dict) -> list[GroupRef]`
  - `effective_residual_ids(index: dict) -> list[str]`
  - `Insight` dataclass：`insight_id / family / kind / payload / canonical_text / evidence / claude_md`
  - `build_corpus_insights(manifest: dict, index: dict) -> list[Insight]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_insights.py
from kb_init.insights import (
    build_corpus_insights,
    effective_residual_ids,
    presentation_groups,
)


def _index(analyses):
    return {"schema_version": "0.1", "run_id": "r", "corpus_hash": "c",
            "vector_doc_ids": [], "chunks": [], "analyses": analyses}


def _analysis(aid, parent, scope, groups, assignments):
    return {"analysis_id": aid, "parent_analysis_id": parent, "input_scope": scope,
            "method": {"params": {}}, "groups": groups, "assignments": assignments,
            "coverage": {"assigned": 0, "ambiguous": 0, "residual": 0},
            "time_axis": {"available": False, "dated_docs": 1, "total_docs": 10,
                          "coverage": 0.1, "threshold": 0.3, "per_group": None}}


def _g(gid, n):
    return {"group_id": gid, "kind": "semantic_topic",
            "member_counts": {"core": n, "halo": 0, "micro": 0, "total_docs": n},
            "representatives": [], "prototype": {}}


def _assigned(doc, gid):
    return {"doc_id": doc, "disposition": "assigned",
            "memberships": [{"group_id": gid, "role": "core", "score": 1.0}],
            "reason_code": None}


def _residual(doc, reason="low_local_density"):
    return {"doc_id": doc, "disposition": "residual", "memberships": [],
            "reason_code": reason}


def test_presentation_replaces_a_subdivided_parent_with_its_children():
    root = _analysis("topics-01", None, {"kind": "all_kept_docs"},
                     [_g("g01", 2), _g("g02", 1)],
                     [_assigned("d1", "g01"), _assigned("d2", "g01"),
                      _assigned("d3", "g02"), _residual("d4")])
    child = _analysis("topics-02", "topics-01",
                      {"kind": "parent_group", "analysis_id": "topics-01",
                       "group_id": "g01"},
                      [_g("g01s01", 1)],
                      [_assigned("d1", "g01s01"),
                       _residual("d2", "subdivision_rejected")])
    refs = presentation_groups(_index([root, child]))
    assert ("topics-01", "g01") not in refs        # 父被替换
    assert ("topics-01", "g02") in refs            # 未被细分的保留
    assert ("topics-02", "g01s01") in refs
    assert len(refs) == 2


def test_presentation_is_ordered_by_size_desc_then_stable():
    root = _analysis("topics-01", None, {"kind": "all_kept_docs"},
                     [_g("g01", 1), _g("g02", 3)],
                     [_assigned("d1", "g01"), _assigned("d2", "g02"),
                      _assigned("d3", "g02"), _assigned("d4", "g02")])
    refs = presentation_groups(_index([root]))
    assert refs == [("topics-01", "g02"), ("topics-01", "g01")]


def test_effective_residual_is_the_union_across_analyses():
    root = _analysis("topics-01", None, {"kind": "all_kept_docs"},
                     [_g("g01", 2)],
                     [_assigned("d1", "g01"), _assigned("d2", "g01"),
                      _residual("d3")])
    child = _analysis("topics-02", "topics-01",
                      {"kind": "parent_group", "analysis_id": "topics-01",
                       "group_id": "g01"},
                      [], [_residual("d1", "under_differentiated_parent"),
                           _residual("d2", "under_differentiated_parent")])
    assert effective_residual_ids(_index([root, child])) == ["d1", "d2", "d3"]


def test_corpus_insights_skip_conditions_that_do_not_hold():
    manifest = {"counts": {"total": 10, "kept": 6, "dropped_stub": 4,
                           "dropped_duplicate": 0},
                "unresolved_links": [], "documents": []}
    root = _analysis("topics-01", None, {"kind": "all_kept_docs"}, [],
                     [_residual(f"d{i}") for i in range(6)])
    kinds = {i.kind for i in build_corpus_insights(manifest, _index([root]))}
    assert "retention" in kinds
    assert "exact_duplicates" not in kinds     # dropped_duplicate == 0 → 不产出
    assert "broken_refs" not in kinds          # unresolved_links 为空 → 不产出


def test_corpus_insights_emit_conditions_that_do_hold():
    manifest = {"counts": {"total": 10, "kept": 6, "dropped_stub": 3,
                           "dropped_duplicate": 1},
                "unresolved_links": [{"from_doc_id": "d1", "target": "a.png"},
                                     {"from_doc_id": "d2", "target": "b.md"}],
                "documents": []}
    root = _analysis("topics-01", None, {"kind": "all_kept_docs"}, [],
                     [_residual(f"d{i}") for i in range(6)])
    out = {i.kind: i for i in build_corpus_insights(manifest, _index([root]))}
    assert "exact_duplicates" in out and "broken_refs" in out
    assert out["broken_refs"].payload["by_kind"] == {"attachment": 1, "document": 1}
    assert "date_blindness" in out             # time_axis.available 为 false


def test_corpus_insights_never_route_to_claude_md():
    manifest = {"counts": {"total": 10, "kept": 6, "dropped_stub": 4,
                           "dropped_duplicate": 0},
                "unresolved_links": [], "documents": []}
    root = _analysis("topics-01", None, {"kind": "all_kept_docs"}, [],
                     [_residual(f"d{i}") for i in range(6)])
    got = build_corpus_insights(manifest, _index([root]))
    assert got, "空列表会让下面的断言恒真"
    assert all(i.claude_md is None for i in got)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.insights'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/insights.py
"""L2 洞察层：把索引的事实编译成人能逐条勾选的洞察。

三族（topic / residual / corpus）不是为了好看：若所有洞察平等计数，回头条件
就会被 corpus 族的统计条目填满而永不触发。人肉 gate 的 12–20 上限按总条数算，
回头条件按 topic 族条数算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GroupRef = tuple[str, str]

ATTACHMENT_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf",
                       ".heic", ".mov", ".mp4", ".zip", ".csv", ".xlsx")


@dataclass(frozen=True)
class Insight:
    insight_id: str
    family: str
    kind: str
    payload: dict
    canonical_text: str
    evidence: dict = field(default_factory=lambda: {"doc_ids": [], "stat": None})
    claude_md: dict | None = None


def _members_by_group(analysis: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a in analysis["assignments"]:
        for m in a["memberships"]:
            out.setdefault(m["group_id"], []).append(a["doc_id"])
    return out


def presentation_groups(index: dict) -> list[GroupRef]:
    """呈现级 group = 未被细分的 group + 全部子分析的 group。

    这条规则只在这里实现一次。让 2C / 2D / 2E 各自解释 analyses 数组，
    三个下游必然长出三套不一致的解释。
    """
    subdivided = {
        (a["input_scope"]["analysis_id"], a["input_scope"]["group_id"])
        for a in index["analyses"][1:]
        if a["input_scope"].get("kind") == "parent_group"
    }
    sized: list[tuple[int, GroupRef]] = []
    for analysis in index["analyses"]:
        members = _members_by_group(analysis)
        for group in analysis["groups"]:
            ref = (analysis["analysis_id"], group["group_id"])
            if ref in subdivided:
                continue
            sized.append((len(members.get(group["group_id"], [])), ref))
    # 篇数降序；同篇数按 ref 升序，保证顺序确定
    return [ref for _, ref in sorted(sized, key=lambda t: (-t[0], t[1]))]


def effective_residual_ids(index: dict) -> list[str]:
    """这次运行实际没有主题的文档 = 各分析 residual 的并集。

    这是**派生量**：analyses[0] 一个字节都没改，父簇成员被折回 residual 这件事
    记在子分析里。下游不许自己拼这个并集。
    """
    ids: set[str] = set()
    for analysis in index["analyses"]:
        for a in analysis["assignments"]:
            if a["disposition"] == "residual":
                ids.add(a["doc_id"])
    assigned_somewhere = {
        a["doc_id"]
        for analysis in index["analyses"]
        for a in analysis["assignments"]
        if a["disposition"] == "assigned"
    }
    return sorted(ids - assigned_somewhere)


def _pct(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.1f}%" if whole else "0.0%"


def build_corpus_insights(manifest: dict, index: dict) -> list[Insight]:
    """语料层事实。条件不成立的一律不产出——不给「你有 0 篇重复文档」这种条目。

    全部 claude_md=None：留存率、断链数对 agent 无用，进 CLAUDE.md 只是噪音。
    """
    counts = manifest["counts"]
    root = index["analyses"][0]
    out: list[Insight] = []
    seq = 0

    def add(kind: str, payload: dict, text: str, stat: dict) -> None:
        nonlocal seq
        seq += 1
        out.append(Insight(f"C{seq}", "corpus", kind, payload, text,
                           {"doc_ids": [], "stat": stat}, None))

    total, kept = counts["total"], counts["kept"]
    add("retention",
        {"total": total, "kept": kept, "dropped_stub": counts["dropped_stub"],
         "dropped_duplicate": counts["dropped_duplicate"]},
        f"读入 {total} 篇，留下 {kept} 篇（{_pct(kept, total)}）；"
        f"{counts['dropped_stub']} 篇是空壳",
        {"total": total, "kept": kept})

    time_axis = root["time_axis"]
    if not time_axis["available"]:
        add("date_blindness",
            {"dated_docs": time_axis["dated_docs"],
             "total_docs": time_axis["total_docs"],
             "coverage": time_axis["coverage"], "threshold": time_axis["threshold"]},
            f"只有 {time_axis['dated_docs']} 篇能确定时间"
            f"（{_pct(time_axis['dated_docs'], time_axis['total_docs'])}）——"
            f"导出包里就没带时间戳，所以这份报告里没有任何时间轴洞察",
            {"coverage": time_axis["coverage"]})

    links = manifest.get("unresolved_links") or []
    if links:
        by_kind = {"attachment": 0, "document": 0}
        for link in links:
            target = (link.get("target") or "").lower()
            key = "attachment" if target.endswith(ATTACHMENT_SUFFIXES) else "document"
            by_kind[key] += 1
        add("broken_refs", {"total": len(links), "by_kind": by_kind},
            f"有 {len(links)} 处引用指向不存在的目标"
            f"（附件 {by_kind['attachment']} / 文档 {by_kind['document']}）",
            {"total": len(links)})

    if counts["dropped_duplicate"]:
        add("exact_duplicates", {"count": counts["dropped_duplicate"]},
            f"{counts['dropped_duplicate']} 篇内容完全相同，已合并",
            {"count": counts["dropped_duplicate"]})

    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/insights.py tests/test_insights.py
git commit -m "feat: 呈现级 group 派生 + corpus 族洞察（条件不成立即不产出）"
```

---

### Task 10: topic 族与 residual 族洞察 + 截断记账

**Files:**
- Modify: `src/kb_init/insights.py`
- Test: `tests/test_insights.py`（追加）

**Interfaces:**
- Consumes: Task 8 的 `extract_keywords`；Task 9 的 `presentation_groups` / `effective_residual_ids` / `Insight`
- Produces:
  - `TOPIC_INSIGHT_CAP = 12`
  - `build_topic_insights(index, bodies, titles, kept_count) -> tuple[list[Insight], dict]`（第二项是 `truncated` 记账）
  - `build_residual_insights(index, bodies, titles, kept_count) -> list[Insight]`
  - `render(insight) -> str`（`canonical_text` 的唯一生成器）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_insights.py 追加
from kb_init.insights import (
    TOPIC_INSIGHT_CAP,
    build_residual_insights,
    build_topic_insights,
    render,
)


def _corpus_index(n_groups, per_group=5, n_residual=10):
    groups, assignments = [], []
    for g in range(n_groups):
        gid = f"g{g + 1:02d}"
        groups.append(_g(gid, per_group))
        for i in range(per_group):
            assignments.append(_assigned(f"g{g}d{i}", gid))
    for i in range(n_residual):
        assignments.append(_residual(f"r{i}"))
    return _index([_analysis("topics-01", None, {"kind": "all_kept_docs"},
                             groups, assignments)])


def _bodies_titles(index):
    bodies, titles = {}, {}
    for a in index["analyses"][0]["assignments"]:
        d = a["doc_id"]
        tag = d[:2]
        bodies[d] = f"{tag}keyword {tag}topic 独有内容{tag} " * 8
        titles[d] = f"标题-{d}"
    return bodies, titles


def test_topic_insights_carry_keywords_evidence_and_share():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    insights, truncated = build_topic_insights(index, bodies, titles, kept_count=25)
    assert len(insights) == 3
    assert truncated["shown"] == 3 and truncated["total"] == 3
    for ins in insights:
        assert ins.family == "topic" and ins.kind == "topic_cluster"
        assert ins.payload["keywords"], "关键词为空会让下面的断言恒真"
        assert len(ins.payload["evidence_doc_ids"]) == 3
        assert ins.payload["doc_count"] == 5
        assert 0 < ins.payload["share_of_kept"] < 1
        assert ins.claude_md == {"section": "focus_areas"}


def test_topic_insights_are_capped_with_full_accounting():
    index = _corpus_index(TOPIC_INSIGHT_CAP + 3)
    bodies, titles = _bodies_titles(index)
    insights, truncated = build_topic_insights(index, bodies, titles,
                                               kept_count=200)
    assert len(insights) == TOPIC_INSIGHT_CAP
    assert truncated["total"] == TOPIC_INSIGHT_CAP + 3
    assert truncated["shown"] == TOPIC_INSIGHT_CAP
    assert len(truncated["omitted_group_refs"]) == 3
    assert truncated["omitted_docs"] == 15          # 3 组 × 5 篇，必须如实记账


def test_residual_insight_reports_the_union_share():
    index = _corpus_index(1, per_group=5, n_residual=15)
    bodies, titles = _bodies_titles(index)
    got = {i.kind: i for i in build_residual_insights(index, bodies, titles,
                                                      kept_count=20)}
    assert "fragment_zone" in got
    assert got["fragment_zone"].payload["count"] == 15
    assert got["fragment_zone"].payload["share_of_kept"] == 0.75


def test_no_residual_insight_when_everything_is_assigned():
    index = _corpus_index(2, per_group=5, n_residual=0)
    bodies, titles = _bodies_titles(index)
    assert build_residual_insights(index, bodies, titles, kept_count=10) == []


def test_canonical_text_equals_render_of_payload():
    """双真源的锁：payload 与 canonical_text 必须始终等价。"""
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    topics, _ = build_topic_insights(index, bodies, titles, kept_count=25)
    residual = build_residual_insights(index, bodies, titles, kept_count=25)
    assert topics and residual
    for ins in [*topics, *residual]:
        assert render(ins) == ins.canonical_text


def test_topic_text_does_not_claim_to_be_a_topic_name():
    """措辞纪律：关键词不是主题名。写成「你的主题是 X」就是产物在撒谎。"""
    index = _corpus_index(1)
    bodies, titles = _bodies_titles(index)
    topics, _ = build_topic_insights(index, bodies, titles, kept_count=15)
    assert "最具区分度的词" in topics[0].canonical_text
    assert "你的主题是" not in topics[0].canonical_text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: FAIL — `ImportError: cannot import name 'TOPIC_INSIGHT_CAP'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/insights.py 追加
TOPIC_INSIGHT_CAP = 12
LONG_ORPHAN_PERCENTILE = 0.80
LONG_ORPHAN_SHOW = 3

_RENDERERS = {}


def _renderer(kind):
    def deco(fn):
        _RENDERERS[kind] = fn
        return fn
    return deco


def render(insight: "Insight") -> str:
    """`canonical_text` 的**唯一**生成器。

    payload 与 canonical_text 双载是为了让 compile 拿到的正是用户审过的那句话；
    双载就必须有一个地方保证两者等价，就是这里。
    """
    return _RENDERERS[insight.kind](insight.payload)


@_renderer("topic_cluster")
def _render_topic(p: dict) -> str:
    return (f"这 {p['doc_count']} 篇里最具区分度的词是 "
            f"{' · '.join(p['keywords'])} — 占 kept {100 * p['share_of_kept']:.1f}%")


@_renderer("fragment_zone")
def _render_fragment(p: dict) -> str:
    return (f"{p['count']} 篇没有形成主题"
            f"（占 kept {100 * p['share_of_kept']:.1f}%）")


@_renderer("long_orphans")
def _render_long_orphans(p: dict) -> str:
    return f"碎片区里有 {p['count']} 篇是长笔记，却没有归入任何主题"


def _group_members(index: dict, ref: GroupRef) -> list[str]:
    analysis = next(a for a in index["analyses"] if a["analysis_id"] == ref[0])
    return sorted(_members_by_group(analysis).get(ref[1], []))


def _evidence_docs(index: dict, ref: GroupRef, members: list[str]) -> list[str]:
    """代表优先取 medoid，不足三篇再按 doc_id 补齐——顺序必须确定。"""
    analysis = next(a for a in index["analyses"] if a["analysis_id"] == ref[0])
    group = next(g for g in analysis["groups"] if g["group_id"] == ref[1])
    picked = [r["doc_id"] for r in group.get("representatives", [])
              if r["doc_id"] in members]
    for d in members:
        if len(picked) >= 3:
            break
        if d not in picked:
            picked.append(d)
    return picked[:3]


def build_topic_insights(
    index: dict, bodies: dict[str, str], titles: dict[str, str], kept_count: int
) -> tuple[list["Insight"], dict]:
    from kb_init.keywords import extract_keywords

    refs = presentation_groups(index)
    shown = refs[:TOPIC_INSIGHT_CAP]
    omitted = refs[TOPIC_INSIGHT_CAP:]

    groups_for_keywords = {f"{a}|{g}": _group_members(index, (a, g)) for a, g in refs}
    keywords = extract_keywords(bodies, groups_for_keywords)

    out: list[Insight] = []
    for n, ref in enumerate(shown, start=1):
        members = _group_members(index, ref)
        evidence = _evidence_docs(index, ref, members)
        payload = {
            "group_ref": {"analysis_id": ref[0], "group_id": ref[1]},
            "keywords": keywords[f"{ref[0]}|{ref[1]}"],
            "doc_count": len(members),
            "share_of_kept": round(len(members) / kept_count, 6) if kept_count else 0.0,
            "evidence_doc_ids": evidence,
            "evidence_titles": [titles.get(d, "") for d in evidence],
        }
        ins = Insight(f"T{n}", "topic", "topic_cluster", payload, "",
                      {"doc_ids": evidence, "stat": None},
                      {"section": "focus_areas"})
        out.append(Insight(**{**ins.__dict__, "canonical_text": render(ins)}))

    # 只写「12 个主题」而隐去遗漏，才是制造虚假完整性。截断本身不说谎。
    truncated = {
        "shown": len(shown),
        "total": len(refs),
        "omitted_group_refs": [{"analysis_id": a, "group_id": g} for a, g in omitted],
        "omitted_docs": sum(len(_group_members(index, r)) for r in omitted),
    }
    return out, truncated


def build_residual_insights(
    index: dict, bodies: dict[str, str], titles: dict[str, str], kept_count: int
) -> list["Insight"]:
    residual = effective_residual_ids(index)
    if not residual:
        return []

    out: list[Insight] = []
    payload = {"count": len(residual),
               "share_of_kept": round(len(residual) / kept_count, 6) if kept_count else 0.0}
    ins = Insight("R1", "residual", "fragment_zone", payload, "",
                  {"doc_ids": [], "stat": {"count": len(residual)}}, None)
    out.append(Insight(**{**ins.__dict__, "canonical_text": render(ins)}))

    lengths = sorted(len(bodies.get(d, "")) for d in bodies)
    if lengths:
        cutoff_idx = int(LONG_ORPHAN_PERCENTILE * (len(lengths) - 1))
        cutoff = lengths[cutoff_idx]
        long_ones = sorted((d for d in residual if len(bodies.get(d, "")) >= cutoff),
                           key=lambda d: (-len(bodies.get(d, "")), d))
        if long_ones:
            evidence = long_ones[:LONG_ORPHAN_SHOW]
            payload = {"count": len(long_ones), "cutoff_chars": cutoff,
                       "evidence_doc_ids": evidence,
                       "evidence_titles": [titles.get(d, "") for d in evidence]}
            ins = Insight("R2", "residual", "long_orphans", payload, "",
                          {"doc_ids": evidence, "stat": {"count": len(long_ones)}},
                          None)
            out.append(Insight(**{**ins.__dict__, "canonical_text": render(ins)}))
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/insights.py tests/test_insights.py
git commit -m "feat: topic 与 residual 族洞察 + 截断全额记账"
```

---

### Task 11: `revisit_gate` + `insights.json` 组装与写盘

**Files:**
- Modify: `src/kb_init/insights.py`
- Test: `tests/test_insights.py`（追加）

**Interfaces:**
- Produces:
  - `INSUFFICIENT_TOPICS_THRESHOLD = 4` / `RESIDUAL_HIGH_THRESHOLD = 0.70` / `GATE_RULES_VERSION = "2b-1"`
  - `build_revisit_gate(topic_count, presentation_group_count, residual_share, corpus_is_first_party) -> dict`
  - `build_insight_set(index, manifest, bodies, titles, *, corpus_is_first_party=True) -> dict`
  - `write_insights(out_dir, payload, markdown) -> None` / `cleanup_insight_files(out_dir)` / `insight_files_remain(out_dir)`
  - `INSIGHT_FILES = ("insights.json", "insights.md")`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_insights.py 追加
import json

import pytest

from kb_init.insights import (
    GATE_RULES_VERSION,
    build_insight_set,
    build_revisit_gate,
    cleanup_insight_files,
    insight_files_remain,
    write_insights,
)


def test_gate_marks_residual_not_evaluable_on_first_party_corpus():
    gate = build_revisit_gate(topic_count=10, presentation_group_count=10,
                              residual_share=0.84, corpus_is_first_party=True)
    states = {c["id"]: c for c in gate["conditions"]}
    assert states["residual_high"]["state"] == "not_evaluable"
    assert states["residual_high"]["reason"] == "requires_third_party_corpus"
    assert states["residual_high"]["prescription"] == "halo"
    assert gate["rules_version"] == GATE_RULES_VERSION


def test_gate_triggers_on_third_party_corpus_with_high_residual():
    gate = build_revisit_gate(10, 10, 0.84, corpus_is_first_party=False)
    states = {c["id"]: c for c in gate["conditions"]}
    assert states["residual_high"]["state"] == "triggered"


def test_gate_topic_conditions_use_topic_count_not_total():
    gate = build_revisit_gate(topic_count=2, presentation_group_count=2,
                              residual_share=0.1, corpus_is_first_party=False)
    states = {c["id"]: c for c in gate["conditions"]}
    assert states["insufficient_topics"]["state"] == "triggered"
    assert states["topics_concentrated"]["state"] == "triggered"
    assert states["insufficient_topics"]["prescription"] == "subdivide"


def test_counts_are_derived_from_the_insight_array():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    manifest = {"counts": {"total": 40, "kept": 25, "dropped_stub": 15,
                           "dropped_duplicate": 0},
                "unresolved_links": [], "documents": []}
    payload = build_insight_set(index, manifest, bodies, titles)
    families = [i["family"] for i in payload["insights"]]
    assert payload["counts"]["total"] == len(payload["insights"])
    assert payload["counts"]["topic"] == families.count("topic")
    assert payload["counts"]["corpus"] == families.count("corpus")


def test_insight_ids_are_unique_and_run_local():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    manifest = {"counts": {"total": 40, "kept": 25, "dropped_stub": 15,
                           "dropped_duplicate": 0},
                "unresolved_links": [], "documents": []}
    payload = build_insight_set(index, manifest, bodies, titles)
    ids = [i["insight_id"] for i in payload["insights"]]
    assert len(set(ids)) == len(ids)
    assert payload["run_id"] == index["run_id"]
    assert payload["corpus_hash"] == index["corpus_hash"]


def test_every_insight_round_trips_render_equals_canonical_text():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    manifest = {"counts": {"total": 40, "kept": 25, "dropped_stub": 15,
                           "dropped_duplicate": 0},
                "unresolved_links": [], "documents": []}
    payload = build_insight_set(index, manifest, bodies, titles)
    assert payload["insights"]
    for item in payload["insights"]:
        assert item["canonical_text"]


def test_is_byte_identical_across_runs():
    index = _corpus_index(3)
    bodies, titles = _bodies_titles(index)
    manifest = {"counts": {"total": 40, "kept": 25, "dropped_stub": 15,
                           "dropped_duplicate": 0},
                "unresolved_links": [], "documents": []}
    a = json.dumps(build_insight_set(index, manifest, bodies, titles),
                   ensure_ascii=False, sort_keys=False)
    b = json.dumps(build_insight_set(index, manifest, bodies, titles),
                   ensure_ascii=False, sort_keys=False)
    assert a == b


def test_write_is_a_sub_transaction(tmp_path, monkeypatch):
    import kb_init.insights as mod

    real = mod.Path.write_text

    def explode(self, *a, **k):
        if self.name == "insights.md":
            raise OSError("写 md 失败")
        return real(self, *a, **k)

    monkeypatch.setattr(mod.Path, "write_text", explode)
    with pytest.raises(OSError):
        write_insights(tmp_path, {"insights": []}, "# md")
    assert not insight_files_remain(tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: FAIL — `ImportError: cannot import name 'GATE_RULES_VERSION'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/insights.py 追加
import json
from dataclasses import asdict
from pathlib import Path

from kb_init import __version__

SCHEMA_VERSION = "0.1"
GATE_RULES_VERSION = "2b-1"
INSUFFICIENT_TOPICS_THRESHOLD = 4
TOPICS_CONCENTRATED_THRESHOLD = 2
RESIDUAL_HIGH_THRESHOLD = 0.70
INSIGHT_FILES = ("insights.json", "insights.md")


def build_revisit_gate(
    topic_count: int,
    presentation_group_count: int,
    residual_share: float,
    corpus_is_first_party: bool = True,
) -> dict:
    """回头条件的**收据**，不是开关：触发不改变任何运行时行为。

    2B 只供数、不自授裁决权——`state` 由本函数按 rules_version 记录的规则算出，
    是可复现的记录，供下一次人类决策使用。

    第三条只在**非本人语料**上可判。拿本人的第二份语料冒充它通过，
    正是这条回头条件想防的自证。
    """
    def cond(cid, threshold, observed, triggered, prescription, reason=None):
        item = {"id": cid, "threshold": threshold, "observed": observed,
                "state": "triggered" if triggered else "not_triggered",
                "prescription": prescription}
        if reason:
            item["state"] = "not_evaluable"
            item["reason"] = reason
        return item

    return {
        "rules_version": GATE_RULES_VERSION,
        "inputs": {
            "topic_insight_count": topic_count,
            "presentation_group_count": presentation_group_count,
            "residual_share": round(residual_share, 6),
            "corpus_is_first_party": corpus_is_first_party,
        },
        "conditions": [
            cond("insufficient_topics", INSUFFICIENT_TOPICS_THRESHOLD, topic_count,
                 topic_count < INSUFFICIENT_TOPICS_THRESHOLD, "subdivide"),
            cond("topics_concentrated", TOPICS_CONCENTRATED_THRESHOLD,
                 presentation_group_count,
                 presentation_group_count <= TOPICS_CONCENTRATED_THRESHOLD,
                 "subdivide"),
            cond("residual_high", RESIDUAL_HIGH_THRESHOLD,
                 round(residual_share, 6),
                 residual_share > RESIDUAL_HIGH_THRESHOLD, "halo",
                 reason=None if not corpus_is_first_party
                 else "requires_third_party_corpus"),
        ],
    }


def build_insight_set(
    index: dict,
    manifest: dict,
    bodies: dict[str, str],
    titles: dict[str, str],
    *,
    corpus_is_first_party: bool = True,
) -> dict:
    from kb_init.keywords import DEFAULT_PARAMS

    kept = manifest["counts"]["kept"]
    topics, truncated = build_topic_insights(index, bodies, titles, kept)
    residual = build_residual_insights(index, bodies, titles, kept)
    corpus = build_corpus_insights(manifest, index)
    items = [*topics, *residual, *corpus]

    families = [i.family for i in items]
    refs = presentation_groups(index)
    residual_share = len(effective_residual_ids(index)) / kept if kept else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": index["run_id"],
        "corpus_hash": index["corpus_hash"],
        "index_schema_version": index["schema_version"],
        "versions": {"kb_init": __version__},
        "naming": {"method": DEFAULT_PARAMS["method"],
                   "params": {k: v for k, v in DEFAULT_PARAMS.items()
                              if k != "method"}},
        "presentation": {
            "group_refs": [{"analysis_id": a, "group_id": g} for a, g in refs],
            "truncated": truncated,
        },
        # counts 由数组派生。独立计数迟早与数组漂移，而漂移没有症状。
        "counts": {"topic": families.count("topic"),
                   "residual": families.count("residual"),
                   "corpus": families.count("corpus"),
                   "total": len(items)},
        "revisit_gate": build_revisit_gate(
            families.count("topic"), len(refs), residual_share,
            corpus_is_first_party),
        "insights": [asdict(i) for i in items],
    }


def write_insights(out_dir: Path, payload: dict, markdown: str) -> None:
    """洞察子事务：两个文件要么都发布，要么都不发布。

    只有 md 没有 json，用户会对着一份永远 validate 不过的清单勾选。
    """
    out_dir = Path(out_dir)
    try:
        (out_dir / "insights.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "insights.md").write_text(markdown, encoding="utf-8")
    except BaseException:
        cleanup_insight_files(out_dir)
        raise


def cleanup_insight_files(out_dir: Path) -> None:
    """逐个独立尝试——连续 unlink 时第一个失败会中断第二个，
    留下的恰恰是最危险的半份产物。"""
    for name in INSIGHT_FILES:
        try:
            (Path(out_dir) / name).unlink(missing_ok=True)
        except OSError:
            pass


def insight_files_remain(out_dir: Path) -> bool:
    return any((Path(out_dir) / name).exists() for name in INSIGHT_FILES)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/insights.py tests/test_insights.py
git commit -m "feat: revisit_gate 三态收据 + insights.json 组装与子事务写盘"
```

---

### Task 12: `insights.md` 渲染 / 解析 / 校验

**Files:**
- Create: `src/kb_init/insights_md.py`
- Test: `tests/test_insights_md.py`

**Interfaces:**
- Produces:
  - `render_markdown(payload: dict) -> str`
  - `parse_markdown(text: str) -> dict`（返回 `{"run_id":…, "corpus_hash":…, "schema_version":…, "selections": {id: bool}}`）
  - `validate_markdown(text: str, payload: dict) -> None`（不合规抛 `InsightsValidationError`，消息含行号）
  - `class InsightsValidationError(ValueError)`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_insights_md.py
import pytest

from kb_init.insights_md import (
    InsightsValidationError,
    parse_markdown,
    render_markdown,
    validate_markdown,
)


def _payload():
    return {
        "schema_version": "0.1", "run_id": "run-1", "corpus_hash": "hash-1",
        "counts": {"topic": 2, "residual": 1, "corpus": 1, "total": 4},
        "insights": [
            {"insight_id": "T1", "family": "topic", "kind": "topic_cluster",
             "canonical_text": "这 9 篇里最具区分度的词是 a · b — 占 kept 3.0%",
             "payload": {"evidence_titles": ["标题一", "标题二", "标题三"]},
             "evidence": {"doc_ids": ["d1", "d2", "d3"], "stat": None},
             "claude_md": {"section": "focus_areas"}},
            {"insight_id": "T2", "family": "topic", "kind": "topic_cluster",
             "canonical_text": "这 5 篇里最具区分度的词是 c · d — 占 kept 1.7%",
             "payload": {"evidence_titles": ["甲", "乙"]},
             "evidence": {"doc_ids": ["d4"], "stat": None},
             "claude_md": {"section": "focus_areas"}},
            {"insight_id": "R1", "family": "residual", "kind": "fragment_zone",
             "canonical_text": "222 篇没有形成主题（占 kept 77.4%）",
             "payload": {}, "evidence": {"doc_ids": [], "stat": None},
             "claude_md": None},
            {"insight_id": "C1", "family": "corpus", "kind": "retention",
             "canonical_text": "读入 620 篇，留下 287 篇（46.3%）；333 篇是空壳",
             "payload": {}, "evidence": {"doc_ids": [], "stat": None},
             "claude_md": None},
        ],
    }


def test_round_trip_preserves_ids_and_all_checked_by_default():
    md = render_markdown(_payload())
    parsed = parse_markdown(md)
    assert parsed["run_id"] == "run-1"
    assert parsed["corpus_hash"] == "hash-1"
    assert parsed["selections"] == {"T1": True, "T2": True, "R1": True, "C1": True}


def test_unchecking_is_the_only_edit_that_survives():
    md = render_markdown(_payload()).replace("- [x] `T2`", "- [ ] `T2`")
    md = md.replace("222 篇没有形成主题", "用户瞎改的文案")
    parsed = parse_markdown(md)
    assert parsed["selections"]["T2"] is False
    assert parsed["selections"]["R1"] is True     # 改正文不影响解析
    validate_markdown(md, _payload())             # 改正文也不该判失败


def test_missing_id_fails_closed_with_line_number():
    md = "\n".join(l for l in render_markdown(_payload()).splitlines()
                   if "`C1`" not in l)
    with pytest.raises(InsightsValidationError, match="C1"):
        validate_markdown(md, _payload())


def test_duplicate_id_fails_closed_with_line_number():
    lines = render_markdown(_payload()).splitlines()
    idx = next(i for i, l in enumerate(lines) if "`T1`" in l)
    lines.insert(idx + 1, lines[idx])
    with pytest.raises(InsightsValidationError, match=r"第 \d+ 行.*T1"):
        validate_markdown("\n".join(lines), _payload())


def test_unknown_id_fails_closed_with_line_number():
    md = render_markdown(_payload()) + "\n- [x] `T9` 不知道哪来的\n"
    with pytest.raises(InsightsValidationError, match=r"第 \d+ 行.*T9"):
        validate_markdown(md, _payload())


def test_cross_run_fails_closed():
    md = render_markdown(_payload())
    other = {**_payload(), "run_id": "run-2"}
    with pytest.raises(InsightsValidationError, match="run_id"):
        validate_markdown(md, other)


def test_cross_corpus_fails_closed():
    md = render_markdown(_payload())
    other = {**_payload(), "corpus_hash": "hash-2"}
    with pytest.raises(InsightsValidationError, match="corpus_hash"):
        validate_markdown(md, other)


def test_broken_header_fails_closed():
    md = render_markdown(_payload()).replace("kb-init:run_id=", "kb-init:runid=")
    with pytest.raises(InsightsValidationError, match="头部"):
        validate_markdown(md, _payload())


def test_ids_are_visible_in_the_rendered_text():
    md = render_markdown(_payload())
    for insight_id in ("T1", "T2", "R1", "C1"):
        assert f"`{insight_id}`" in md


def test_sections_are_grouped_by_family_with_counts():
    md = render_markdown(_payload())
    assert "## 主题（2 条）" in md
    assert "## 碎片区（1 条）" in md
    assert "## 语料（1 条）" in md


def test_empty_insight_set_renders_a_valid_header_only_document():
    empty = {**_payload(), "insights": [],
             "counts": {"topic": 0, "residual": 0, "corpus": 0, "total": 0}}
    md = render_markdown(empty)
    assert parse_markdown(md)["selections"] == {}
    validate_markdown(md, empty)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_insights_md.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb_init.insights_md'`

- [ ] **Step 3: 最小实现**

```python
# src/kb_init/insights_md.py
"""`insights.md` 的**唯一**真源：渲染、解析、校验都在这里。

渲染与解析拆成两个模块、由两处各写一半，是格式漂移最经典的来源；
放在同一个模块里，round-trip 测试才拦得住。

用户**只应该改 `[x]` / `[ ]`**。正文一律不被信任——compile 按 ID 从 json 取。
"""
from __future__ import annotations

import re

_HEADER = re.compile(
    r"<!--\s*kb-init:run_id=(?P<run_id>\S+)\s+corpus_hash=(?P<corpus_hash>\S+)"
    r"\s+schema_version=(?P<schema_version>\S+)\s*-->"
)
_ITEM = re.compile(r"^- \[(?P<mark>[x ])\] `(?P<id>[A-Za-z]+\d+)`")

_SECTIONS = (("topic", "主题"), ("residual", "碎片区"), ("corpus", "语料"))


class InsightsValidationError(ValueError):
    """校验失败一律 fail closed，且必须带行号——「有一条对不上」而不说哪一条，
    用户只能全文肉眼比对。"""


def render_markdown(payload: dict) -> str:
    lines = [
        "# kb-init — 洞察确认清单",
        "",
        f"<!-- kb-init:run_id={payload['run_id']} "
        f"corpus_hash={payload['corpus_hash']} "
        f"schema_version={payload['schema_version']} -->",
        "",
        "> 只改 `[x]` / `[ ]`。改正文不会生效——`compile` 按 ID 从 insights.json 取正文。",
        "> 改完跑 `kb-init compile`，或先跑 `kb-init validate insights.md` 单独校验。",
        "",
    ]
    by_family: dict[str, list[dict]] = {}
    for item in payload["insights"]:
        by_family.setdefault(item["family"], []).append(item)

    for family, title in _SECTIONS:
        items = by_family.get(family, [])
        if not items:
            continue
        lines += [f"## {title}（{len(items)} 条）", ""]
        for item in items:
            lines.append(f"- [x] `{item['insight_id']}` {item['canonical_text']}")
            evidence_titles = (item.get("payload") or {}).get("evidence_titles") or []
            if evidence_titles:
                shown = " · ".join(t.replace("\n", " ") for t in evidence_titles)
                lines.append(f"      证据：{shown}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_markdown(text: str) -> dict:
    header = _HEADER.search(text)
    selections: dict[str, bool] = {}
    for line in text.splitlines():
        match = _ITEM.match(line)
        if match:
            selections[match.group("id")] = match.group("mark") == "x"
    return {
        "run_id": header.group("run_id") if header else None,
        "corpus_hash": header.group("corpus_hash") if header else None,
        "schema_version": header.group("schema_version") if header else None,
        "selections": selections,
    }


def validate_markdown(text: str, payload: dict) -> None:
    header = _HEADER.search(text)
    if header is None:
        raise InsightsValidationError(
            "头部标记缺失或被改坏：找不到 <!-- kb-init:run_id=… --> 那一行。"
            "请用本次运行产出的 insights.md 重新开始。"
        )
    if header.group("run_id") != payload["run_id"]:
        raise InsightsValidationError(
            f"run_id 不匹配：文件是 {header.group('run_id')}，"
            f"insights.json 是 {payload['run_id']}——这是两次不同运行的产物。"
        )
    if header.group("corpus_hash") != payload["corpus_hash"]:
        raise InsightsValidationError(
            f"corpus_hash 不匹配：文件是 {header.group('corpus_hash')}，"
            f"insights.json 是 {payload['corpus_hash']}——语料已经变了。"
        )

    known = {i["insight_id"] for i in payload["insights"]}
    seen: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _ITEM.match(line)
        if not match:
            continue
        insight_id = match.group("id")
        if insight_id in seen:
            raise InsightsValidationError(
                f"第 {lineno} 行：ID {insight_id} 重复（首次出现在第 {seen[insight_id]} 行）"
            )
        if insight_id not in known:
            raise InsightsValidationError(
                f"第 {lineno} 行：未知 ID {insight_id}，insights.json 里没有这一条"
            )
        seen[insight_id] = lineno

    missing = sorted(known - set(seen))
    if missing:
        raise InsightsValidationError(
            f"清单里缺少这些 ID：{'、'.join(missing)}。"
            "绝不静默少编几条——请用本次运行产出的 insights.md 重新开始。"
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_insights_md.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/insights_md.py tests/test_insights_md.py
git commit -m "feat: insights.md 渲染/解析/校验合一——失败一律 fail closed 且带行号"
```

---

### Task 13: 洞察阶段接进 pipeline + manifest + 退出码 6

**Files:**
- Modify: `src/kb_init/pipeline.py`、`src/kb_init/manifest.py:26-50`、`src/kb_init/cli.py:42-84`
- Test: `tests/test_index_pipeline.py`、`tests/test_cli.py`（追加）

**Interfaces:**
- Consumes: Task 5 的 `read_index`；Task 11 的 `build_insight_set` / `write_insights` / `cleanup_insight_files` / `insight_files_remain`；Task 12 的 `render_markdown`
- Produces:
  - `pipeline._run_insights_stage(staging, docs, *, index_status) -> tuple[str, str | None]`
  - `write_manifest(..., insights_status="skipped", insights_reason=None)`
  - `run()` 返回值新增 `insights_status` / `insights_reason`
  - CLI 退出码 6

- [ ] **Step 1: 写失败测试**

```python
# tests/test_index_pipeline.py 追加
import json

from kb_init.pipeline import run
from tests.fakes import BrokenEmbedder, FakeEmbedder


def test_insights_are_published_alongside_the_index(tmp_path):
    src = _corpus(tmp_path, [("alpha", 12, "aaa"), ("beta", 12, "bbb")])
    out = tmp_path / "out"
    summary = run(src, out, embedder=FakeEmbedder(), run_id="t")
    assert summary["insights_status"] == "complete"
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "t"
    assert payload["counts"]["total"] == len(payload["insights"])
    assert (out / "insights.md").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["insights_status"] == "complete"
    assert manifest["insights_reason"] is None


def test_insights_md_validates_against_its_own_json(tmp_path):
    from kb_init.insights_md import validate_markdown

    src = _corpus(tmp_path, [("alpha", 12, "aaa")])
    out = tmp_path / "out"
    run(src, out, embedder=FakeEmbedder(), run_id="t")
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    validate_markdown((out / "insights.md").read_text(encoding="utf-8"), payload)


def test_no_index_skips_insights(tmp_path):
    src = _corpus(tmp_path, [("alpha", 6, "aaa")])
    out = tmp_path / "out"
    summary = run(src, out, no_index=True)
    assert summary["insights_status"] == "skipped"
    assert summary["insights_reason"] == "no_index"
    assert not (out / "insights.json").exists()
    assert not (out / "insights.md").exists()


def test_index_failure_skips_insights_and_keeps_exit_semantics(tmp_path):
    src = _corpus(tmp_path, [("alpha", 12, "aaa")])
    out = tmp_path / "out"
    summary = run(src, out, embedder=BrokenEmbedder("nan"), run_id="t")
    assert summary["index_status"] == "failed"
    assert summary["insights_status"] == "skipped"
    assert summary["insights_reason"] == "index_failed"
    assert (out / "knowledge").is_dir()


def test_insights_failure_keeps_the_index_and_marks_status(tmp_path, monkeypatch):
    import kb_init.insights as mod

    monkeypatch.setattr(mod, "build_insight_set",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸")))
    src = _corpus(tmp_path, [("alpha", 12, "aaa")])
    out = tmp_path / "out"
    summary = run(src, out, embedder=FakeEmbedder(), run_id="t")
    assert summary["index_status"] == "complete"
    assert summary["insights_status"] == "failed"
    assert (out / "index.json").exists()
    assert not (out / "insights.json").exists()
    assert not (out / "insights.md").exists()
```

```python
# tests/test_cli.py 追加
def test_exit_code_6_when_only_insights_failed(tmp_path, monkeypatch, capsys):
    from kb_init.cli import main

    monkeypatch.setattr(
        "kb_init.pipeline.run",
        lambda *a, **k: {"total": 10, "kept": 6, "dropped_stub": 4,
                         "dropped_duplicate": 0, "index_status": "complete",
                         "index_reason": None, "insights_status": "failed",
                         "insights_reason": "naming_failed"},
    )
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 6
    assert "洞察" in capsys.readouterr().err


def test_exit_code_5_still_wins_when_index_failed(tmp_path, monkeypatch):
    from kb_init.cli import main

    monkeypatch.setattr(
        "kb_init.pipeline.run",
        lambda *a, **k: {"total": 10, "kept": 6, "dropped_stub": 4,
                         "dropped_duplicate": 0, "index_status": "failed",
                         "index_reason": "model_unavailable",
                         "insights_status": "skipped",
                         "insights_reason": "index_failed"},
    )
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_index_pipeline.py tests/test_cli.py -q`
Expected: FAIL — `KeyError: 'insights_status'`

- [ ] **Step 3: 最小实现**

`src/kb_init/pipeline.py` 新增窄边界阶段：

```python
_INSIGHTS_FAILURE_REASONS = (
    (ImportError, "runtime_unavailable"),
    (OSError, "io_failed"),
    (ValueError, "contract_violation"),
)


def _classify_insights_failure(exc: Exception) -> str:
    """与 _classify_index_failure 同一条纪律：**必须是全函数**，任何输入都只返回
    枚举值。它跑在 except 分支里，自己抛出就会把产物一起带走。"""
    for exc_type, reason in _INSIGHTS_FAILURE_REASONS:
        if isinstance(exc, exc_type):
            return reason
    return "naming_failed"


def _run_insights_stage(
    staging: Path, docs: list, *, index_status: str
) -> tuple[str, str | None]:
    """洞察阶段。失败必须在这里被吸收成状态——理由与索引阶段完全相同。"""
    if index_status == "skipped":
        return "skipped", "no_index"
    if index_status != "complete":
        return "skipped", "index_failed"

    try:
        from kb_init.index import read_index
        from kb_init.insights import (
            build_insight_set,
            cleanup_insight_files,
            insight_files_remain,
            write_insights,
        )
        from kb_init.insights_md import render_markdown
        from kb_init.manifest import read_manifest

        index, _matrix = read_index(staging)
        kept = [d for d in docs if d.status == "kept"]
        bodies = {d.doc_id: d.body for d in kept}
        titles = {d.doc_id: (d.title or "") for d in kept}
        manifest_like = {
            "counts": __import__("kb_init.clean", fromlist=["summarize"]).summarize(docs),
            "unresolved_links": _unresolved_links_cache.get("value", []),
            "documents": [],
        }
        payload = build_insight_set(index, manifest_like, bodies, titles)
        write_insights(staging, payload, render_markdown(payload))
        return "complete", None
    except Exception as exc:
        reason = _classify_insights_failure(exc)
        try:
            from kb_init.insights import cleanup_insight_files, insight_files_remain

            cleanup_insight_files(staging)
            if insight_files_remain(staging):
                raise OSError("洞察半成品无法清除")
        except ImportError:
            pass
        return "failed", reason
```

> **实现提示**：上面 `manifest_like` 的拼法是占位写法，不要照抄。真正的做法是把
> `run()` 里已经算好的 `result.unresolved_links` 与 `summarize(docs)` 作为参数
> 显式传进来——`_run_insights_stage(staging, docs, counts=…, unresolved_links=…,
> index_status=…)`。**洞察阶段跑在 `write_manifest` 之前**，此时 manifest 还没落盘，
> 不能去读它。

`run()` 里在索引阶段之后、`write_manifest` 之前插入：

```python
        insights_status, insights_reason = _run_insights_stage(
            staging, docs, counts=summarize(docs),
            unresolved_links=result.unresolved_links,
            index_status=index_status,
        )
```

`write_manifest(...)` 加两个参数，`summary` 加两个字段：

```python
        summary["insights_status"] = insights_status
        summary["insights_reason"] = insights_reason
```

`src/kb_init/manifest.py` 的 `write_manifest` 签名末尾加
`insights_status: str = "skipped", insights_reason: str | None = None`，
payload 里在 `index_reason` 之后加这两个键。

`src/kb_init/cli.py` 在现有退出码 5 分支**之后**追加：

```python
    # 6 与 5 的恢复动作不同：5 要重跑索引（需要网络与模型），6 只差洞察层。
    # 拓宽 5 的语义会让脚本在只需重算洞察时错误地重跑整个索引。
    if counts.get("insights_status") == "failed":
        print(
            f"警告：清洗产物与索引已写入，但洞察未生成"
            f"（{counts.get('insights_reason')}）。",
            file=sys.stderr,
        )
        return 6
```

并把顶部退出码注释补上 6。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/pipeline.py src/kb_init/manifest.py src/kb_init/cli.py \
        tests/test_index_pipeline.py tests/test_cli.py
git commit -m "feat: 洞察阶段接进 pipeline + manifest 记账 + 退出码 6"
```

---

### Task 14: `kb-init validate` 子命令

**Files:**
- Modify: `src/kb_init/cli.py`
- Test: `tests/test_cli.py`（追加）

**Interfaces:**
- Produces: `kb-init validate <insights.md>`；同目录找 `insights.json`；通过返回 0，失败打印带行号的原因并返回 7

> 用 7 而不是复用 6：6 是"这次运行的洞察没生成"，7 是"你手上这份清单不合法"，
> 二者的下一步动作完全不同（重跑 vs 改文件）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli.py 追加
import json

from kb_init.cli import main


def _write_pair(tmp_path):
    payload = {
        "schema_version": "0.1", "run_id": "r1", "corpus_hash": "c1",
        "counts": {"topic": 1, "residual": 0, "corpus": 0, "total": 1},
        "insights": [{"insight_id": "T1", "family": "topic",
                      "kind": "topic_cluster", "canonical_text": "文本",
                      "payload": {}, "evidence": {"doc_ids": [], "stat": None},
                      "claude_md": None}],
    }
    from kb_init.insights_md import render_markdown

    (tmp_path / "insights.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    md = render_markdown(payload)
    (tmp_path / "insights.md").write_text(md, encoding="utf-8")
    return payload


def test_validate_accepts_a_matching_pair(tmp_path, capsys):
    _write_pair(tmp_path)
    assert main(["validate", str(tmp_path / "insights.md")]) == 0
    assert "1 条" in capsys.readouterr().out


def test_validate_rejects_unknown_id_with_line_number(tmp_path, capsys):
    _write_pair(tmp_path)
    path = tmp_path / "insights.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n- [x] `T9` 冒出来的\n",
                    encoding="utf-8")
    assert main(["validate", str(path)]) == 7
    err = capsys.readouterr().err
    assert "T9" in err and "行" in err


def test_validate_reports_missing_json_clearly(tmp_path, capsys):
    _write_pair(tmp_path)
    (tmp_path / "insights.json").unlink()
    assert main(["validate", str(tmp_path / "insights.md")]) == 7
    assert "insights.json" in capsys.readouterr().err


def test_normal_run_still_works_with_subcommand_parser(tmp_path):
    """加子命令最容易踩的坑：把原来的 `kb-init <source>` 用法弄坏。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("# a\n\n" + "内容 " * 50, encoding="utf-8")
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-index"]) == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: FAIL — `validate` 被当成 source 路径，返回 3

- [ ] **Step 3: 最小实现**

在 `main()` 最开头、`build_parser()` **之前**插入分流。不用 argparse 子命令：
现有用法 `kb-init <source>` 是位置参数，改成 subparsers 会破坏它（上面最后一条测试盯的就是这个）。

```python
def _validate_command(md_path: str) -> int:
    import json
    from pathlib import Path

    from kb_init.insights_md import InsightsValidationError, validate_markdown

    md = Path(md_path)
    json_path = md.with_name("insights.json")
    if not md.exists():
        print(f"错误：找不到 {md}", file=sys.stderr)
        return 7
    if not json_path.exists():
        print(f"错误：同目录下找不到 insights.json（{json_path}）。"
              f"校验需要两份文件配对。", file=sys.stderr)
        return 7
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        validate_markdown(md.read_text(encoding="utf-8"), payload)
    except InsightsValidationError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 7
    except (OSError, ValueError) as exc:
        print(f"错误：读取失败——{exc}", file=sys.stderr)
        return 7
    print(f"校验通过：{len(payload['insights'])} 条洞察全部对得上。")
    return 0
```

`main()` 开头：

```python
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "validate":
        if len(argv) != 2:
            print("用法：kb-init validate <insights.md>", file=sys.stderr)
            return 2
        return _validate_command(argv[1])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/kb_init/cli.py tests/test_cli.py
git commit -m "feat: kb-init validate 子命令（退出码 7，不与 6 混用）"
```

---

### Task 15: 真实语料验收

**Files:**
- Modify: `tests/test_real_corpus.py`
- Create: `probes/insight_quality_probe.py`

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 真实语料断言（`skipif` 语料不存在）+ 一个人工验收探针

**背景数据（spec §2.1 / §2.4 / §3.2 实测，用于写断言）：**

| | kept | 主分析簇数 | 被标记 | 呈现级主题 | 有效 residual |
|---|---|---|---|---|---|
| Apple Notes | 287 | 5 | **0** | 5 | 222（77.4%） |
| Notion | 757 | 2 | **1**（509 篇那个） | 10 | 637（84.1%） |

- [ ] **Step 1: 写失败测试**

```python
# tests/test_real_corpus.py 追加
import json
import os
from pathlib import Path

import pytest

APPLE = Path(os.path.expanduser("~/Documents/Obsidian Vault/Archive/Apple Notes"))
NOTION_PARENT = Path(os.path.expanduser("~/Documents/notion-export"))


def _notion_dir():
    if not NOTION_PARENT.is_dir():
        return None
    for child in sorted(NOTION_PARENT.iterdir()):
        if child.is_dir() and child.name.startswith("Export-"):
            return child
    return None


@pytest.mark.skipif(not APPLE.is_dir(), reason="Apple Notes 语料不在本机")
def test_apple_notes_has_no_flagged_group(tmp_path):
    """选择性验证：检测器不能把好簇也标记掉。这是它的负例。"""
    from kb_init.pipeline import run

    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-apple")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert len(index["analyses"]) == 1, "Apple Notes 上不应有任何 group 被细分"

    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    assert payload["counts"]["topic"] == 5
    assert 10 <= payload["counts"]["total"] <= 13
    gate = {c["id"]: c for c in payload["revisit_gate"]["conditions"]}
    assert gate["residual_high"]["state"] == "not_evaluable"


@pytest.mark.skipif(_notion_dir() is None, reason="Notion 语料不在本机")
def test_notion_blob_is_subdivided_into_nameable_topics(tmp_path):
    from kb_init.pipeline import run

    out = tmp_path / "out"
    run(_notion_dir(), out, run_id="acceptance-notion")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert len(index["analyses"]) == 2, "那个 509 篇的簇必须被标记并细分"
    child = index["analyses"][1]
    assert child["input_scope"]["kind"] == "parent_group"

    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    assert payload["counts"]["topic"] >= 8
    gate = {c["id"]: c for c in payload["revisit_gate"]["conditions"]}
    assert gate["topics_concentrated"]["state"] == "not_triggered"
    assert gate["insufficient_topics"]["state"] == "not_triggered"


@pytest.mark.skipif(not APPLE.is_dir(), reason="Apple Notes 语料不在本机")
def test_real_insights_md_round_trips(tmp_path):
    """合成语料测不出真实形态——真实标题里有 emoji、换行、markdown 字符，
    渲染出来必须仍然能被自己的解析器读回去。"""
    from kb_init.insights_md import parse_markdown, validate_markdown
    from kb_init.pipeline import run

    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-apple-md")
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    md = (out / "insights.md").read_text(encoding="utf-8")
    validate_markdown(md, payload)
    parsed = parse_markdown(md)
    assert set(parsed["selections"]) == {i["insight_id"] for i in payload["insights"]}
    assert all(parsed["selections"].values())


@pytest.mark.skipif(not APPLE.is_dir(), reason="Apple Notes 语料不在本机")
def test_every_topic_insight_has_nonempty_keywords_and_evidence(tmp_path):
    """反恒真：只断言「证据 ⊆ 成员」时，证据为空也能全绿。"""
    from kb_init.pipeline import run

    out = tmp_path / "out"
    run(APPLE, out, run_id="acceptance-apple-kw")
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    topics = [i for i in payload["insights"] if i["family"] == "topic"]
    assert topics
    for item in topics:
        assert item["payload"]["keywords"], item["insight_id"]
        assert len(item["payload"]["evidence_doc_ids"]) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_real_corpus.py -q`
Expected: 语料在本机则 FAIL（尚未跑通真实数据）；不在则 SKIP

- [ ] **Step 3: 实现**

本任务不写产品代码——它是验收。跑上面的测试，**若断言不成立，回到对应任务修实现**，
不要改断言去迁就结果。三条最可能需要回头的线索：

1. `topic` 条数与预期不符 → 检查 `presentation_groups` 的父簇替换逻辑（Task 9）。
2. Apple Notes 出现被标记的 group → 检测器阈值或 residual 基线取错（Task 1）。
3. 关键词为空 → `global_df_cap` 太紧（Task 8），按 spec §4.3 在 0.05–0.20 间调，
   **并把最终值写回 `DEFAULT_PARAMS`**，让它随产物落盘。

再写人工验收探针（**不进 CI**，输出含真实标题，只在本机看）：

```python
# probes/insight_quality_probe.py
"""人工验收：把每条 topic 洞察的关键词与证据标题打出来，人判断认不认得出。

不进 CI，也不写任何断言——"簇认得出"是人工验收标准，拿自动断言冒充它，
等于用一个恒真的检查换掉真正的验收。

用法：
    .venv/bin/python probes/insight_quality_probe.py <kb-out 目录>
"""
import json
import sys
from pathlib import Path


def main() -> int:
    out = Path(sys.argv[1])
    payload = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    titles = {d["doc_id"]: d["title"] for d in manifest["documents"]}

    topics = [i for i in payload["insights"] if i["family"] == "topic"]
    print(f"呈现级主题 {len(topics)} 条"
          f"（总洞察 {payload['counts']['total']} 条）\n")
    for item in topics:
        p = item["payload"]
        print(f"[{item['insight_id']}] {' · '.join(p['keywords'])}  "
              f"— {p['doc_count']} 篇")
        for doc_id in p["evidence_doc_ids"]:
            print(f"      {titles.get(doc_id, '?')}")
        print()

    truncated = payload["presentation"]["truncated"]
    if truncated["shown"] != truncated["total"]:
        print(f"⚠️ 截断：显示 {truncated['shown']} / 共 {truncated['total']}，"
              f"未列出 {truncated['omitted_docs']} 篇")

    gate = payload["revisit_gate"]
    print("回头条件：")
    for c in gate["conditions"]:
        print(f"  {c['id']:22s} {c['state']:15s} "
              f"observed={c['observed']} threshold={c['threshold']}")
    print("\n请人工判断：上面每组关键词，认得出是什么主题吗？"
          "（验收线：≥70%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑验收**

```bash
.venv/bin/python -m pytest -q                       # 全量，含真实语料
.venv/bin/python -m pytest -q -m smoke              # 真实模型烟测
.venv/bin/python probes/insight_quality_probe.py ~/tmp/kb-out-apple
.venv/bin/python probes/insight_quality_probe.py ~/tmp/kb-out-notion
```

Expected: 全量通过；探针输出的关键词组 ≥70% 能被认出。把两份探针输出存到
**仓库外**（`assistant-output/kb-init-r2/`），不要进 git。

- [ ] **Step 5: Commit**

```bash
git add tests/test_real_corpus.py probes/insight_quality_probe.py
git commit -m "test: 2B 真实语料验收 + 人工命名质量探针"
```

---

### Task 16: 文档同步

**Files:**
- Modify: `README.md`、`docs/DESIGN.md`、`STATUS.md`、`docs/superpowers/specs/2026-08-15-2a-index-layer-design.md`、`CLAUDE.md`

- [ ] **Step 1: README**

退出码表加两行：

```
| 6 | 清洗产物与索引已发布，但洞察层未生成 |
| 7 | `validate` 判定 insights.md 不合法（改文件后重跑，不必重跑索引） |
```

产物列表加 `insights.json`（不可编辑真源）与 `insights.md`（勾选清单）；
命令列表加 `kb-init validate <insights.md>`。

- [ ] **Step 2: DESIGN §5**

在 L2 小节的警示块后补一句：三类时间轴洞察按 2B spec §3.5 推迟，解除条件是
出现 `time_axis.available == true` 的目标语料；L2 在导出类语料上的主体是主题。

- [ ] **Step 3: 2A spec §2.1**

把"触发即回来加 halo（方案 C）"替换为 2B spec §2.2 的条件→处方映射表，并注明：
②已于 2026-08-15 触发并以 2A′ 处置；③在现有两份语料上 `not_evaluable`（都是本人语料）。

- [ ] **Step 4: STATUS.md**

「当前阶段」改为 2B 已完成；「最近进展」加两条：回头条件②触发与 2A′ 处置、
2B 洞察层与两份合同落地；「历史里程碑」加一条。

- [ ] **Step 5: CLAUDE.md**

`Plan 2 拆成五块` 那行把 2B 标为已完成。**不要**新增段落——
该文件的价值在于短，硬不变量已经覆盖本轮的教训。

- [ ] **Step 6: 提交前检查并 Commit**

```bash
git grep "$(printf '/Us''ers/')" && echo "❌ 有绝对路径" || echo "✓ 无绝对路径"
.venv/bin/python -m pytest -q
git add README.md docs/DESIGN.md STATUS.md CLAUDE.md \
        docs/superpowers/specs/2026-08-15-2a-index-layer-design.md
git commit -m "docs: 同步 2B 的退出码/产物/回头条件处方映射"
```

---

## Self-Review

**1. Spec coverage**

| spec 节 | 实现于 |
|---|---|
| §2.3 检测器 | Task 1 |
| §2.4 二次细分 + 子簇复检 + `analyses[0]` 不变 | Task 2 / 3 / 4 / 6 |
| §2.5 不做 halo | Task 11（`not_evaluable`）+ Task 16（2A spec 修订） |
| §3.1 三族 | Task 9 / 10 |
| §3.2 洞察清单与条件门 | Task 9（corpus）/ Task 10（topic·residual） |
| §3.3 呈现级派生（两个公共函数） | Task 9 |
| §3.4 截断记账 | Task 10 |
| §3.5 推迟项 | Task 16（DESIGN 注记）；无代码 |
| §4 关键词管线 | Task 7 / 8 |
| §4.5 验收线 | Task 15（探针） |
| §5 `insights.json` 合同 | Task 11 |
| §6 `insights.md` 合同 | Task 12 |
| §7 `revisit_gate` | Task 11 |
| §8 架构与写盘后读回 | Task 5 / 13 |
| §9 错误处理与退出码 6 | Task 13 / 14 |
| §10 三层测试网 | 各任务 Step 1 + Task 15 |
| §12 文档变更 | Task 16 |

**2. Placeholder scan**：无 TBD / TODO；每个代码步骤都给了可运行代码。
Task 13 的 `manifest_like` 段落**显式标注了是占位写法并给出正确做法**，
不是遗留的占位符。

**3. Type consistency**

- `GroupRef = tuple[str, str]`，Task 9 定义，Task 10 使用，一致。
- `cluster_documents(..., cluster_selection_method=, group_id_prefix=)`：Task 2 定义，Task 3 使用，一致。
- `subdivide_group(group_id, member_ids, rows, baseline_cohesion, *, min_cluster_size, min_samples, lift_min)`：Task 3 定义，Task 6 使用，参数名一致。
- `build_analysis(*, analysis_id, parent_analysis_id, input_scope, groups, assignments, method, time_axis)`：Task 4 定义，Task 6 使用，一致。
- `read_index(out_dir) -> (dict, ndarray)`：Task 5 定义，Task 13 使用，一致。
- `extract_keywords(bodies, groups, *, top_k, params)`：Task 8 定义，Task 10 使用，一致。
- `render(insight)` 只在 `insights.py` 内；`render_markdown(payload)` 只在 `insights_md.py` 内——两个名字刻意不同，避免混用。
- `Insight` 字段名 `insight_id / family / kind / payload / canonical_text / evidence / claude_md` 在 Task 9 定义，Task 10 / 11 / 12 全部按此拼写。
