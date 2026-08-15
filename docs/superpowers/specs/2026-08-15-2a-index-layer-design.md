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
`index.json` + 向量产物。**不产任何洞察文字，不给簇起名。**

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
| `chunk.py` | 文档 → 块（**产生**映射，不写盘）；分块由注入的 splitter 决定 | 无 | 模型、聚类、写盘 |
| `embed.py` | 块文本 → 向量 → 按 doc 均值池化 + L2 归一；产出前验证形状/数值 | fastembed | 聚类、Document、写盘 |
| `cluster.py` | 文档向量矩阵 + doc_id 列表 → assignments（含 residual 拒答） | scikit-learn | 文本、Document、写盘 |
| `index.py` | 组装 `index.json`（纯 builder）+ **唯一持久化**入口 | 上三者 | — |

沿用 Plan 1 的约定：**`index.py` 是本层唯一写盘的模块**（对应 `emit.py` 在 Plan 1 的地位）。
因此 `chunk.py` 的职责措辞是"**产生**映射"而非"持久化映射"——两者不能同时成立。

`cluster.py` 只吃 `np.ndarray` 和 `list[str]`——换聚类算法不碰解析层，也让它可以被单独测试而不需要
任何模型。

### 3.1 两个协议（为了可测与 token 安全）

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> Iterable[np.ndarray]: ...

class Splitter(Protocol):
    """把正文切成不超过模型 token 上限的片段，返回 (start, end) 偏移对。"""
    def split(self, text: str) -> list[tuple[int, int]]: ...
```

**为什么分块必须可注入而不是写死 400 字符**：DESIGN §7 把"不分块 → 长笔记静默截断"列为硬约束，
而 400 字符只是**中文近似 1 字 1 token 的启发式**。英文、代码、罕见 Unicode、长符号串都可能在 400
字符内突破 512 token 上限——那正是这条硬约束要防的事，用启发式挡它等于没挡。

默认实现 `TokenSafeSplitter` 用真实 tokenizer 计数（fastembed 暴露的 tokenizer；若该 API 不可用，
降级为按脚本类型区分的保守字符上限，并在 `method` 里如实记录用的是哪种）。测试注入确定性 fake。

**偏移单位 = Python 原生 `str` 索引（Unicode code point）**，不是字节。`knowledge/*.md` 一律 UTF-8，
重建时 `text[start:end]` 即原块。这条必须写死，否则跨语言语料上偏移会错位。

### 3.2 进度提示不由 embed.py 打印

`embed.py` 通过 callback 上报进度事件（模型名 / 体积 / 已完成块数），**由 CLI 决定怎么显示**。
库调用者与测试都不该被迫吞掉 stdout。

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
  "versions": {"kb_init": "…", "python": "…", "numpy": "…", "scipy": "…",
               "sklearn": "…", "onnxruntime": "…", "embedder_adapter": "fastembed-0.8.0"},
  "vector_doc_ids": ["d123", "d124"],
  "chunks": [{"chunk_id": "c0001", "doc_id": "d123", "start": 0, "end": 380}],
  "analyses": [{
    "analysis_id": "topics-01",
    "parent_analysis_id": null,
    "input_scope": {"kind": "all_kept_docs"},
    "method": {
      "family": "density",
      "name": "hdbscan",
      "model": "BAAI/bge-small-zh-v1.5",
      "model_revision": "…",
      "params": {"min_cluster_size": 5, "min_samples": 5, "metric": "euclidean"},
      "seed": 0,
      "splitter": {"name": "token_safe", "max_tokens": 512, "fallback_used": false},
      "pooling": "mean_l2",
      "score_kind": "density_membership",
      "score_direction": "higher_better",
      "decision_threshold": null
    },
    "groups": [{
      "group_id": "g01",
      "kind": "semantic_topic",
      "member_counts": {"core": 33, "halo": 0, "micro": 0, "total_docs": 33},
      "representatives": [{"doc_id": "d123", "kind": "medoid"}],
      "prototype": {"kind": "mean_of_members", "member_role": "core", "metric": "cosine"}
    }],
    "assignments": [
      {"doc_id": "d123", "disposition": "assigned",
       "memberships": [{"group_id": "g01", "role": "core", "score": 0.91}],
       "reason_code": null},
      {"doc_id": "d124", "disposition": "residual",
       "memberships": [], "reason_code": "low_local_density"}
    ],
    "coverage": {"assigned": 65, "ambiguous": 0, "residual": 222},
    "time_axis": {"dated_docs": 39, "total_docs": 757, "coverage": 0.052,
                  "threshold": 0.30, "available": false, "per_group": null}
  }]
}
```

### 合同条款（这些是"不能被后续推翻"的部分）

- **`analyses` 从第一天就是数组**。2A 只产一项，但 D（residual 二次微聚类）要求同时保留
  "第一轮的 residual"与"第二轮的 micro assigned"两套 disposition——单顶层结构表达不了，
  等到那时再改就是破坏性迁移。`input_scope` 现在填 `all_kept_docs`，D 填"父分析的 residual"。
- **`group_id` 的引用一律是 `(analysis_id, group_id)` 二元组**，不假设全局唯一。
- **`memberships` 必须是数组**。兼容单归属（A）、无归属（B）、多标签（E）。
  **多个 membership ≠ `ambiguous`**——E 的重叠是正常状态；`ambiguous` 专指"够得着多个但都不够格"。
- **`disposition` 独立于 memberships**，取值 `assigned` / `ambiguous` / `residual`。
  "没有归属"是一等状态，不是空值的副作用。
- **每个 kept doc 恰有一条 assignment**，`coverage` 三项必须由 assignments 派生而非独立计数
  （否则两者会漂移）。
- **`role`** 取值 `hard` / `core` / `halo` / `micro` / `member`（最后一个给 E 的 motif 用）。2A 只产 `core`。
- **`score_kind` + `score_direction` 必存**。KMeans 距离是 lower_better，HDBSCAN probability 是
  higher_better——不记方向，下游无法解释分数，更无法跨 analysis 比较。`decision_threshold` 记录
  实际生效的判定阈值（2A 为 `null`，C 的 halo 门槛落在这里）。
- **`groups` 用 role-aware 的 `member_counts` 而不是单一 `size`**。C 引入 halo 后 `size` 说不清含不含
  halo；E 的重叠会让各 group 之和超过文档总数。`total_docs` 是去重后的文档数。
- **`representatives` + `prototype` 现在就产出**。它们不是内部细节：DESIGN §5 明确要求 L3 用
  "kNN / 簇代表"生成候选而**绝不遍历所有文档对**——代表物是上游合同的一部分。存 `doc_id` 引用
  而不是 512 维向量，JSON 不背这个体积。
- **`groups` 不带 label**（见 §2.4）。
- **`chunks` 只存偏移**，正文可由 `knowledge/*.md` + 偏移重建。体积与隐私都占便宜。
- **`vector_doc_ids` 显式记录矩阵行 → doc_id**。不用"按 doc_id 升序"这种约定：切不出块的
  文档有 assignment 却没有向量行，两者数量本就可以不等，靠约定推断行归属迟早错位，
  而错位没有任何症状。
- **`versions` 记 python / numpy / scipy / sklearn / onnxruntime**，`embedder_adapter` 由
  **适配器自报**——注入假实现时仍写 fastembed，或管线自建的真适配器被记成 injected，
  都是产物在撒谎。⚠️ 已知边界：`model_revision` 是 repo + 文件路径，不是权重的内容哈希，
  同一路径理论上可对应不同权重；实际由 `embedder_adapter` 的版本钉住。

### 与 Plan 1 产物的绑定

`corpus_hash` 与 `run_id` 取自同一次运行的 manifest。下游（2B/2C/2D）读 `index.json` 时若
`corpus_hash` 与 manifest 不符 → **fail closed**（DESIGN §4.2 已有此原则，此处沿用）。

## 6. 向量产物（不是缓存）

`out/index-vectors.npy` — float32 矩阵，**行序按 doc_id 升序**（不用 assignments 的出现顺序：
那个顺序由聚类结果决定，会随参数变化）。

**它是可重建的下游产物，不是跨运行缓存。** 这里此前写过一套"缓存失效判定"，是自相矛盾的——
Plan 1 要求输出目录必须为空，所以 `out/` 里的 `.npy` **永远不可能被下一次运行命中**，那套判定逻辑
一次也不会执行。v0.1 不做跨运行缓存；需要反复调聚类参数时用 `probes/cluster_quality_probe.py`
的 `--cache`，那是探针层的事。

体积可控（757 × 512 × 4B ≈ 1.5MB；1925 篇约 3.9MB）。删掉它不影响 `index.json` 的可读性。

**完整性校验**：读取方（2B 及以后）必须校验 `.npy` 的 shape 与 `analyses[0].assignments` 的文档数
一致、dtype 为 float32、无 NaN/Inf——文件被截断时 shape 仍可能"看起来合理"，只比对元数据不够。

## 7. 错误处理

**核心原则（来自 DESIGN §4.3）**：索引失败不得使清洗产物报废。这与 Plan 1 的"整次运行原子"不冲突——
原子性保证的是"发布动作只有一次 rename"，不是"所有可选产物都必须齐全"。

### 7.1 控制流：索引失败必须在 pipeline 内被吸收

**这一条是实现层最容易踩的坑，必须写死。** Plan 1 的 `run()` 用 `ExitStack` 注册了
`published or rmtree(staging)`——**rename 之前传播出去的任何异常都会删掉 staging，清洗产物一并消失**。
因此若在 CLI 外层捕获 embedding 异常再返回 5，那时产物早已不存在，退出码 5 是个谎。

固定控制流：

```
1. 清洗产物写入 staging（Plan 1 现有流程）
2. 在 pipeline 内以窄边界运行索引阶段
   ├ 成功        → index_status = "complete"
   ├ 失败        → 删除全部 index 半成品，index_status = "failed"，记稳定 reason_code
   └ --no-index  → index_status = "skipped"
3. 最后写定 manifest（含 index_status 与 reason_code）
4. 唯一一次 rename ← commit 点
5. run() 返回结构化结果（含 index_status）
6. CLI 在 run() **正常返回后**把 failed 映射为退出码 5 —— 绝不在 commit 点之后 raise
```

Plan 1 在 `pipeline.py` 里那句"commit 点后不做任何可能失败的事"依然成立：rename 之后不再有 I/O，
只是调用方可以依据**已经返回的状态**选择退出码 5。

**索引是一个子事务**：`index.json` 与 `index-vectors.npy` 要么都发布，要么都不发布。
JSON 写成而向量写失败（或反之）必须回滚成"没有任何 index 文件"。

**`index_status` 必须落在 manifest 里**。只看"有没有 index.json"分不清 skipped / failed / 旧版本产物，
事后诊断不能只靠 stderr 和退出码。

### 7.2 失败模式表

| 失败模式 | 行为 | 退出码 |
|---|---|---|
| 模型下载失败（无网 / 代理 / HF 限流） | 发布清洗产物，`index_status=failed`，reason `model_unavailable` | **5** |
| fastembed / onnxruntime 导入失败 | 同上，reason `runtime_unavailable`，提示可能是平台 wheel 缺失（R15） | 5 |
| ONNX session 创建失败 / OOM / 模型缓存损坏 / batch 中途抛错 | 同上，reason `inference_failed` | 5 |
| embedding 输出非法：数量≠文本数、跨 batch 维度不一致、空/二维异常、NaN/Inf、零范数、dtype 错 | **fail closed**，视为 `inference_failed`，绝不把坏向量写进产物 | 5 |
| index 文件写失败（JSON 或 .npy），但能清理并完成 manifest + rename | 回滚 index 子事务，发布清洗产物 | 5 |
| emit / manifest / staging 清理 / 最终 rename 失败 | 沿用 Plan 1：不发布任何东西 | 4 |
| 语料篇数 < `min_cluster_size` × 2 | 不是错误：`groups: []`，全部 residual，reason `corpus_too_small` | 0 |
| kept 篇数为 0 | 不是错误：**照常写一份合法的空索引**（`assignments: []` / `vector_doc_ids: []`）。绝不允许"complete 却没有 index 文件"这种说谎状态 | 0 |
| 文档切出 0 个块（正文全空白） | 补一条 `empty_document` 的 residual；它有 assignment 但没有向量行，靠 `vector_doc_ids` 表达 | 0 |
| 单个字符的 token 数就超上限 | 显式报错（`contract_violation`）——默默放行等于又一次静默截断 | 5 |
| tokenizer 的 truncation 关不掉 | 降级为字符切分并**如实**记 `fallback_used: true`，不许自称 token-safe | 0 |
| 聚类结果全为 residual | 不是错误：合法结果，照常写盘 | 0 |
| `KeyboardInterrupt` / `SystemExit` | **不吸收、不伪装成 partial success**；照常清理 staging，不产生正式输出 | 130 / 透传 |
| `--no-index` | 不导入 fastembed、不联网、不写 index 文件，`index_status=skipped` | 0 |

退出码 5 是本层新增，需同步 README。**5 表示"你要的东西拿到了，但索引没做成"**——脚本可据此重跑，
而不是把它当成整体失败。

**`index_reason` 必须是稳定枚举**，不能是异常类名（那是实现细节，换个库就漂移）：
`runtime_unavailable` / `model_unavailable` / `inference_failed` / `io_failed` /
`contract_violation`。

### 7.3 commit 点前后的纪律

除了「索引失败要被吸收」，还有三处会制造**产物已发布但命令报错**，必须一并排除：

1. **返回值在 commit 之前算好**。`summarize()` 放在 rename 之后算，一旦抛错就是这个现象。
2. **临时目录在 rename 之前主动清掉**。交给 `ExitStack` / `TemporaryDirectory` 在 `run()`
   返回时清理，清理失败同样发生在 commit 之后。
3. **staging 的清理条件用「未发布」判定，且 `rmtree(ignore_errors=True)`**。rename 成功与
   置位之间被 Ctrl-C 打断时，staging 路径已不存在，清理必须是无害的。

## 8. 测试策略

**硬约束：单元测试绝不下载模型。** `embed.py` 暴露一个最小协议

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> Iterable[np.ndarray]: ...
```

真实实现包 fastembed；测试注入确定性的 fake（例如按文本 hash 生成固定向量），这样池化、聚类、
序列化全部可测且秒级。

但 **fake 不能是唯一的 embedding 测试层**——真实模型才暴露的问题（维度不符、归一化差异、
超 token 上限被静默截断）会整批逃过测试网。三层补网：

**第一层：无模型的对抗式 fake 单测**（秒级，进 CI）

| 层 | 测什么 |
|---|---|
| `chunk.py` | 边界（正好整除 / 空文档 / 超长单块 / 单个 CJK 字符超限）；`doc_id → chunk_id` 完整无重复；`text[start:end]` 能逐字重建原块 |
| `embed.py` | 均值池化 + L2 归一的数学正确性；**对抗注入**：少一个向量、维度错、跨 batch 维度变化、NaN、Inf、零向量、生成器中途抛错——每一种都必须 fail closed 而不是写出坏产物 |
| `cluster.py` | residual 拒答确实产生 `disposition: "residual"`；语料过小 / 全 residual 不抛异常；同 seed 同结果 |
| `index.py` | 合同级校验：group 引用可解析、ID 唯一、**每个 kept doc 恰有一条 assignment**、`coverage` 由 assignments 派生且自洽、`member_counts` 与 memberships 对得上、偏移可重建、`.npy` shape 与文档数一致 |
| CLI / pipeline | `--no-index` 不触发 embedding 也不导入 fastembed；**故障注入**：分别在写 .npy 前、写 JSON 前、manifest 定稿前抛错，断言最终结果只有两种——"完整 index"或"无任何 index 文件的清洗产物"，不存在中间态 |
| 真实语料（skipif） | 跑通；`time_axis.available` 在两份导出语料上为 `false`；coverage 自洽 |

fake 的向量用 **SHA-256 派生**，不用 Python 内置 `hash()`（后者带进程级随机盐，测试会随机飘）。

**第二层：一个真实模型 smoke lane**（不进常规 CI，按需 / 发布前跑）
预热并锁定模型缓存后**断网**执行，断言：revision 与维度与记录一致 / 输出数量与 dtype 与有限性合规 /
**用真实 tokenizer 验证每个块都不超 512 token** / 同输入重复执行结果稳定在容差内。
这一层是唯一能挡住"400 字符启发式在英文与代码上失效"的网。

**第三层：可复现性**（2A 的第二条验收标准，自动测试）
仅"排序后比较"不够——HDBSCAN 的原始 label 与浮点序列化都会引入差异。规定：
输入矩阵按 doc_id 排序 → cluster label 按**稳定簇签名**（成员 doc_id 集合的哈希）重编号 →
groups/assignments/memberships 全部 canonical sort → score 固定精度序列化。
并加一条"**随机打乱输入顺序，结果仍相同**"的测试。
可复现性的保证边界限定在 `versions` 记录的依赖版本内。

**"簇认得出"是人工验收**，用 `probes/cluster_quality_probe.py` 完成，不进 CI。

## 9. 对既有文档的变更项

实施时一并处理，避免文档与行为脱节：

1. **README 退出码表**：新增 5。
2. **README 选项表**：新增 `--no-index`。
2b. **manifest 新增 `index_status`**（`complete` / `failed` / `skipped`）与 `index_reason`。
3. **DESIGN §7「L1/L2 纯本地，秒出」**：改为诚实表述——清洗秒出，索引首次运行需下载模型并按分钟计。
4. **DESIGN §5「L2 轨迹」**：注明三类时间轴洞察受 §2.2 的条件门约束，在导出类语料上通常不可用。
5. **DESIGN §13**：把"69–77% 未归类**说明语料本身稀疏**"降级为经得起检验的弱版本——
   *在当前分块与均值池化下，这三个模型之间的选择不是主要瓶颈*。强版本尚缺三项证据：
   三模型共享同一套 mean pooling 可能一起失败；同一组 HDBSCAN 参数不等于对每个表示空间做过公平校准；
   缺少对随机抽取的 residual 文档的人工审计。并记录最便宜的证伪实验（抽 60 篇盲测能否人工成组 +
   查 top-5 邻居，无需重跑 embedding）。

## 10. 验收标准

1. 全量测试通过，且第一层（对抗式 fake）测试不下载模型、秒级跑完。
2. 同输入 + 同 method → 相同 assignments，且**打乱输入顺序结果不变**（自动测试断言）。
3. 在 Notion（1925 篇）与 Apple Notes（620 篇）上跑通，`time_axis.available` 均为 `false`，
   `coverage` 三项之和等于 kept 篇数。
4. `--no-index` 路径不产生任何网络请求、不导入 fastembed，耗时与 Plan 1 持平。
   索引失败时清洗产物仍然发布，`manifest.index_status == "failed"`，退出码为 5。
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
