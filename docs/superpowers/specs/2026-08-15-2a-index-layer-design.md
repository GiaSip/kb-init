# 2A 索引层 — 设计 spec

> 日期：2026-08-15 ｜ 状态：设计定稿，待实施计划
> 上游：`docs/DESIGN.md` §4（架构）/ §5（洞察分层）/ §7（技术决策）/ §13（R2 验收结论）

## 1. 这是什么

Plan 2（洞察与编译）被拆成五个子项目，本 spec 只覆盖第一个：

| | 子项目 | 独立验收标准 |
|---|---|---|
| **2A** | **索引层**（本文档） | 簇能被人一眼认出 + 同输入可复现 |
| 2B | L2 洞察 + `insights.json`/`insights.md` 合同 | 12–20 条洞察，每条挂 doc_id 证据 |
| 2D | `compile` → CLAUDE.md | 只收勾选项，正文从 json 取 |
| 2C | Wrapped 呈现层 `report.html` | 能发出去，脱敏版不漏私密字段 |
| 2E | L3 耦合洞察（需用户 key） | 每条可溯源，L3 挂了不毁前序产物 |

顺序 2A → 2B → 2D → 2C → 2E。2D 先于 2C，因为 DESIGN §4.2 把裁决权给了档案线，而人肉 gate 靠的是
`insights.md` 这个纯文本 checklist，不依赖 `report.html`。

**2A 的职责**：读 Plan 1 的产物 `knowledge/*.md` → 分块 → 本地 embedding → 聚类 → 产出
`index.json` + 向量缓存。**不产任何洞察文字，不给簇起名。**

## 2. 已决事项与依据

### 2.1 默认聚类 = HDBSCAN core-only，其余路线留给 schema

R2 验收（DESIGN §13）在 287 篇真实语料上比过三个模型 × 两种方法。外部 review（Codex 5.6-Sol）指出
A（KMeans 强制入簇）/ B（HDBSCAN + 噪声桶）是个假二选一，还有：

- **C** 核心 + 有门槛的 halo 归属（带拒答的 soft clustering）
- **D** residual 二次微聚类（`leaf` 模式，只收 3–10 篇的小簇）
- **E** 放弃互斥聚类，改多标签 motif 轴
- **F** 把「主题数」与「洞察数」解耦（这是**呈现策略**，不是聚类方法）

关键结论：**只要 schema 允许索引层"明确拒绝归属"，选哪条路就不再是昂贵决定**——A/B/C/D/E 全都能在同一份
合同里表达，而「要不要把 residual 提升成一条洞察」退化成 2B 的决定。

因此 2A **只实现 B**（HDBSCAN core-only），schema 按能容纳全部五条路来设计。

> **回头条件（写死在此，避免"以后再说"变成"永远不说"）**：若 2B 完成后出现下列任一情况，回到 2A 加 halo（方案 C）：
> ① 12–20 条洞察凑不满；② 洞察全部挤在 ≤2 个主题上；③ residual 比例在第二份非贾老师语料上仍 >70%。

### 2.2 时间轴 = 条件洞察，不是必然产物

实测三份语料的日期可解析率：

| 语料 | kept | 有日期 |
|---|---|---|
| Notion 导出 | 757 | **5.2%** |
| Apple Notes 导出 | 287 | **6.3%** |
| 已维护的 Obsidian Wiki（对照组） | 470 | 43% |

根因已挖到底，**不是解析器不行，是导出包里就没有**：Notion 只有数据库页面才带 `Created:` 行
（537 篇像样的 md 中仅 19 篇）；176 个 CSV 里 10 个带日期列，总共只能对上 18/1925 个 md；
mtime 早被 DESIGN §5.1 证伪。

DESIGN §5 的 L2 有四类洞察，**三类依赖时间轴**（兴趣迁移曲线 / 半衰期 / 沉默主题）。因此：

- 2A **计算并记录**日期覆盖率（全局），按阈值 `0.30` 置 `time_axis.available`。
  **0.30 的依据**：实测三份语料分成泾渭分明的两档——导出类 5–6%，已维护类 43%，中间是空的。
  阈值取在空档里，任何落在 0.10–0.40 的值在现有证据下行为相同。它是**可配置常量而非调参结果**，
  写在 `index.json` 的 `time_axis.threshold` 里随产物走，将来有第三类语料时可据实修订
- **仅当 `available` 为真**才计算 per-group 时间统计
- 是否输出为洞察、如何标注样本量，属于 2B
- 效果：烂语料上自动消失，优等生语料上自动出现，**无需分支代码**

### 2.3 索引进主流程 + `--no-index` 快速通道

DESIGN §4 的叙事是"跑一次，拿走产物"，所以索引是主流程第 4 步而非独立命令。代价是首次运行要下载
~90MB 模型并跑几分钟 CPU——这正是 R14 点名的风险，且与 §7"L1/L2 秒出"的表述冲突。

处理：`--no-index` 让只要清洗产物的人几秒拿到且不下载任何东西；首次下载明确可见（模型名 / 体积 /
预估）；§7 的"秒出"改为诚实表述（见 §9 文档变更项）。

**不做**（YAGNI）：独立 `kb-init index` 命令（重调聚类参数用已有的 `probes/cluster_quality_probe.py`，
它已支持 `--cache`）；halo / 二次聚类 / motif；面向用户的检索功能（DESIGN Non-goals 已排除）。

### 2.4 2A 不给簇起名

起名是语义判断，属于 2B（可能还需要 L3）。2A 只保证"这些文档在一起"这个事实。
这条边界让 `cluster.py` 完全不需要认识文本。

## 3. 架构

| 模块 | 职责 | 依赖 | 不认识 |
|---|---|---|---|
| `chunk.py` | 文档 → 块（只记偏移），持久化 `doc_id → chunk_id` | 无 | 模型、聚类 |
| `embed.py` | 块 → 向量 → 均值池化 + L2 归一 → 文档向量；封装模型获取与首次运行提示 | fastembed | 聚类、Document |
| `cluster.py` | 文档向量矩阵 + doc_id 列表 → assignments（含 residual 拒答） | scikit-learn | 文本、Document |
| `index.py` | 组装并写 `index.json` + 向量缓存；记录可复现三要素 | 上三者 | — |

沿用 Plan 1 的约定：**`index.py` 是本层唯一写盘的模块**（对应 `emit.py` 在 Plan 1 的地位）。

`cluster.py` 只吃 `np.ndarray` 和 `list[str]`——换聚类算法不碰解析层，也让它可以被单独测试而不需要
任何模型。

## 4. 数据流

```
knowledge/*.md
  → chunk.py   → [Chunk(chunk_id, doc_id, start, end)]        只记偏移，不复制正文
  → embed.py   → 块向量 → 按 doc 均值池化 → L2 归一 → (doc_ids, matrix)
  → cluster.py → [Assignment(doc_id, disposition, memberships, reason_code)]
  → index.py   → out/index.json + out/index-vectors.npy
```

全部在 Plan 1 的 staging 目录内完成，跟着那一次 `rename` 一起发布——**保住"整次运行原子"这个不变量**。

## 5. `index.json` 合同

```json
{
  "schema_version": "0.1",
  "run_id": "…",
  "corpus_hash": "…",
  "analysis_id": "topics-01",
  "parent_analysis_id": null,
  "method": {
    "family": "density",
    "name": "hdbscan",
    "model": "BAAI/bge-small-zh-v1.5",
    "model_revision": "…",
    "params": {"min_cluster_size": 5, "min_samples": 5, "metric": "euclidean"},
    "seed": 0,
    "chunk_chars": 400,
    "pooling": "mean_l2"
  },
  "chunks": [{"chunk_id": "c0001", "doc_id": "d123", "start": 0, "end": 400}],
  "groups": [{"group_id": "g01", "kind": "semantic_topic", "size": 33}],
  "assignments": [
    {"doc_id": "d123", "disposition": "assigned",
     "memberships": [{"group_id": "g01", "role": "core",
                      "score": 0.91, "score_kind": "density_membership"}],
     "reason_code": null},
    {"doc_id": "d124", "disposition": "residual",
     "memberships": [], "reason_code": "low_local_density"}
  ],
  "coverage": {"assigned": 65, "ambiguous": 0, "residual": 222},
  "time_axis": {"dated_docs": 39, "total_docs": 757, "coverage": 0.052,
                "threshold": 0.30, "available": false, "per_group": null}
}
```

### 合同条款（这些是"不能被后续推翻"的部分）

- **`memberships` 必须是数组**。兼容单归属（A）、无归属（B）、多标签（E）。
- **`disposition` 独立于 memberships**，取值 `assigned` / `ambiguous` / `residual`。
  "没有归属"是一等状态，不是空值的副作用。
- **`role`** 取值 `hard` / `core` / `halo` / `micro`，为 C/D 预留。2A 只产 `core`。
- **`score_kind` 必存**。KMeans 距离、HDBSCAN probability、cosine、关键词权重不能假装是同一种分数。
- **二次聚类用新的 `analysis_id` + `parent_analysis_id`，不覆盖第一轮事实**。
  2A 只有一轮，两个字段**现在就写进顶层**（`parent_analysis_id: null`）——现在加是零成本，
  等到需要第二轮再加就是破坏性变更。引入多轮时升 `schema_version` 并把顶层这组字段收进 `index_runs[]`。
- **`groups` 不带 label**（见 §2.4）。
- **`chunks` 只存偏移**，正文可由 `knowledge/*.md` + 偏移重建。体积与隐私都占便宜。

### 与 Plan 1 产物的绑定

`corpus_hash` 与 `run_id` 取自同一次运行的 manifest。下游（2B/2C/2D）读 `index.json` 时若
`corpus_hash` 与 manifest 不符 → **fail closed**（DESIGN §4.2 已有此原则，此处沿用）。

## 6. 向量缓存

`out/index-vectors.npy` — float32 矩阵，**行序按 doc_id 升序**（不是 assignments 的出现顺序——
那个顺序由聚类结果决定，会随参数变化，拿它当行序等于让缓存依赖聚类，本末倒置）。

**它是可安全删除的缓存，不是合同的一部分**：删掉只是下次要重跑 embedding，`index.json` 自身完整可读。
体积可控（757 × 512 × 4B ≈ 1.5MB；1925 篇约 3.9MB）。

缓存有效性由 `index.json` 的 `corpus_hash` + `method.model` + `method.model_revision` +
`method.chunk_chars` + `method.pooling` 共同判定，任一不符即视为失效并重算——**不做部分复用**。

## 7. 错误处理

**核心原则（来自 DESIGN §4.3）**：索引失败不得使清洗产物报废。这与 Plan 1 的"整次运行原子"不冲突——
原子性保证的是"发布动作只有一次 rename"，不是"所有可选产物都必须齐全"。

| 失败模式 | 行为 | 退出码 |
|---|---|---|
| 模型下载失败（无网 / 代理 / HF 限流） | 发布清洗产物（无 `index.json`），stderr 说明原因与补救 | **5**（新增：产物已发布但索引未完成） |
| fastembed / onnxruntime 导入失败 | 同上，提示可能是平台 wheel 缺失（R15） | 5 |
| 语料篇数 < `min_cluster_size` × 2 | 不是错误：`groups: []`，全部 residual，`reason_code: "corpus_too_small"` | 0 |
| 聚类结果全为 residual | 不是错误：合法结果，照常写盘 | 0 |
| 向量缓存与当前 method/corpus 不符 | 忽略缓存重算，不报错 | 0 |
| 写盘失败 | 沿用 Plan 1 合同 | 4 |
| `--no-index` | 不导入 fastembed、不联网、不写 `index.json` | 0 |

退出码 5 是本层新增，需同步 README 的退出码表。**5 表示"你要的东西拿到了，但索引没做成"**——
脚本可据此重跑，而不是把它当成整体失败。

## 8. 测试策略

**硬约束：单元测试绝不下载模型。** `embed.py` 暴露一个最小协议

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> Iterable[np.ndarray]: ...
```

真实实现包 fastembed；测试注入确定性的 fake（例如按文本 hash 生成固定向量），这样池化、聚类、
序列化全部可测且秒级。

| 层 | 测什么 |
|---|---|
| `chunk.py` | 边界（正好整除 / 空文档 / 超长单块）；`doc_id → chunk_id` 映射完整且无重复；偏移能重建原文 |
| `embed.py` | 均值池化 + L2 归一的数学正确性（注入 fake）；块数与 chunk 表一致；不触网 |
| `cluster.py` | residual 拒答确实产生 `disposition: "residual"`；语料过小时不抛异常；同 seed 同结果 |
| `index.py` | schema 完整性（必需字段全在）；`corpus_hash` 与 manifest 一致；缓存失效判定 |
| CLI / pipeline | `--no-index` 不触发 embedding；索引失败时清洗产物仍发布且退出码为 5 |
| 真实语料（skipif） | 跑通；`time_axis.available` 在两份导出语料上为 `false`；coverage 字段存在且自洽 |

**可复现性测试**是 2A 的第二条验收标准，必须是自动测试而非人工：同输入 + 同 `method` → 逐字节相同的
`assignments`（排序后比较，避免字典序噪音）。

**"簇认得出"是人工验收**，用 `probes/cluster_quality_probe.py` 完成，不进 CI。

## 9. 对既有文档的变更项

实施时一并处理，避免文档与行为脱节：

1. **README 退出码表**：新增 5。
2. **README 选项表**：新增 `--no-index`。
3. **DESIGN §7「L1/L2 纯本地，秒出」**：改为诚实表述——清洗秒出，索引首次运行需下载模型并按分钟计。
4. **DESIGN §5「L2 轨迹」**：注明三类时间轴洞察受 §2.2 的条件门约束，在导出类语料上通常不可用。
5. **DESIGN §13**：把"69–77% 未归类**说明语料本身稀疏**"降级为经得起检验的弱版本——
   *在当前分块与均值池化下，这三个模型之间的选择不是主要瓶颈*。强版本尚缺三项证据：
   三模型共享同一套 mean pooling 可能一起失败；同一组 HDBSCAN 参数不等于对每个表示空间做过公平校准；
   缺少对随机抽取的 residual 文档的人工审计。并记录最便宜的证伪实验（抽 60 篇盲测能否人工成组 +
   查 top-5 邻居，无需重跑 embedding）。

## 10. 验收标准

1. 全量测试通过，且新增测试不下载模型、可在秒级跑完。
2. 同输入 + 同 method → 相同 assignments（自动测试断言）。
3. 在 Notion（1925 篇）与 Apple Notes（620 篇）上跑通，`time_axis.available` 均为 `false`，
   `coverage` 三项之和等于 kept 篇数。
4. `--no-index` 路径不产生任何网络请求，耗时与 Plan 1 持平。
5. 人工验收：`probes/cluster_quality_probe.py` 给出的簇与 `index.json` 的 groups 一致，
   且至少 3 个簇能被一句话命名。
6. Codex 终审判定可合并。

## 11. 风险

| 风险 | 处理 |
|---|---|
| residual 比例过高导致 2B 洞察不足 | §2.1 的回头条件已写死，触发即回来加 halo |
| HDBSCAN 参数在别人的语料上不适用 | 参数进 `method` 落盘，可复现可对比；不在 2A 做跨语料调参 |
| 首次运行体验（R14） | `--no-index` + 可见下载进度；GitHub Releases 单二进制仍在 v0.2 路线 |
| 跨平台 wheel（R15） | 导入失败降级为退出码 5 而非崩溃；CI 验平台留在发布前 |
