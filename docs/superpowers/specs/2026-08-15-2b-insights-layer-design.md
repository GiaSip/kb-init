# 2B L2 洞察层 + insights 合同 — 设计 spec

> 日期：2026-08-15 ｜ 状态：设计定稿，待实施计划
> 上游：`docs/DESIGN.md` §4.2（验收闭环）/ §5（洞察分层）/ §6（CLAUDE.md 产出）/ §13（R2 结论）
> 前序：`2026-08-15-2a-index-layer-design.md`（索引层，已合并）
>
> ⚠️ 本文只写量化结论与脱敏描述。含真实笔记标题的簇样本与复现命令留在仓库外
> （沿用 DESIGN §13 的处置：`assistant-output/kb-init-r2/`），不进开源历史。

## 1. 这是什么

2A 备齐了索引层的**事实**（groups / assignments / residual / representatives / time_axis 条件门），
2B 定的是**呈现策略**：把这些事实变成 12–20 条人能逐条勾选的洞察，并冻结 `insights.json` /
`insights.md` 两份合同——它们是 2C（report.html）、2D（compile → CLAUDE.md）、2E（L3）共同的上游。

2B **不产 HTML、不产 CLAUDE.md**。它产两份文件加一个校验器。

### 1.1 本 spec 包含一段 2A 的前置修正

2A spec §2.1 写死的回头条件**已在第二份语料上触发**（详见 §2）。按当时的约定，2B 不能绕过它继续做，
所以 §2 是 2A′ 的设计，实施时作为**独立 commit 先落**，2B 的实现建立在它之上。

## 2. 前置：2A′ 过大簇细分（回头条件②已触发）

### 2.1 触发的事实

在两份真实语料上跑完整索引（已合并配置：HDBSCAN `min_cluster_size=5, min_samples=5`,
sklearn 默认 `cluster_selection_method='eom'`）：

| 语料 | kept | 簇数 | 最大簇 | residual |
|---|---|---|---|---|
| Apple Notes 导出 | 287 | 5 | 32（11.1%） | 222（77.4%） |
| Notion 导出 | 757 | **2** | **509（67.2%）** | 243（32.1%） |

Notion 上那个 509 篇的簇随机抽 18 篇（`seed=0`，可复现），内容横跨界面组件、设计史、
中国思想史、投资笔记、AI 产品分析——**没有任何非空泛标签能覆盖**。

逐条比对 2A spec §2.1 的三条回头条件：

| 条件 | 判定 | 依据 |
|---|---|---|
| ① topic 族洞察凑不满 | **触发** | Notion 只有 2 个 group，topic 族至多 2 条 |
| ② 洞察全部挤在 ≤2 个主题上 | **触发** | Notion 字面就是 2 个 group |
| ③ residual 在第二份**非本人**语料上仍 >70% | **not_evaluable** | 两份语料都是本人的；Notion 在当前配置下是 32.1%，不是 >70% |

> 这三条判定描述的是 **2A′ 之前**的状态。§7 的 `revisit_gate` 示例是 2A′ **之后**重新评估的结果，
> 两者数字不同是预期行为——回头条件的作用就是被修复后不再触发。

③ 不可评估这件事必须如实记账，不能拿本人的第二份语料冒充"非本人语料"来宣布它通过或失败。

### 2.2 处方修正：②的对症解法不是 halo

2A spec 写的是"触发即回来加 halo（方案 C）"。这个映射对①②是错配的：

- **halo** 把 residual 文档以低置信度挂进**已有的**簇 → 提高覆盖率，**不产生新主题**。
- Notion 的病是"只有 2 个主题且其中一个是大杂烩"，加 halo 只会让那个大杂烩更大。

所以修正为**条件 → 处方**的显式映射，写进产物（§7）：

| 条件 | 病灶 | 处方 |
|---|---|---|
| ① 主题数量不足 | 分化不足 | **D′ 过大簇细分**（本节） |
| ② 主题分布集中 | 分化不足 | **D′ 过大簇细分**（本节） |
| ③ residual 比例过高 | 覆盖率不足 | **C halo 归属**（本 spec 不做，见 §2.5） |

### 2.3 检测器：内聚度提升量，而不是簇的绝对大小

"多大算过大"用篇数比例（>50% kept？>30%？）会引入一个只能在这两份语料上调出来的魔数。
改用**语料自校准**的判据：把每个簇的内聚度与**本语料 residual 集合**的内聚度相比。
residual 按定义就是"没有主题的一堆"，它天然是这份语料的**无主题基线**。

```
cohesion(S) = mean_{d∈S} cos(v_d, centroid(S))       centroid 为成员向量均值后 L2 归一
lift(g)     = cohesion(members(g)) − cohesion(residual)
```

两份语料实测：

| | n | cohesion | lift |
|---|---|---|---|
| Apple g01–g05 | 5–32 | 0.931–0.955 | **+0.208 … +0.231** |
| Notion g02 | 5 | 0.932 | **+0.182** |
| Notion g01（巨簇） | 509 | 0.819 | **+0.069** |
| （Notion residual 基线） | 243 | 0.750 | — |

六个正常簇落在 +0.18…+0.23，巨簇落在 +0.069，**中间是空的**。
阈值 `COHESION_LIFT_MIN = 0.12` 取在这个空档里——与 2A 给 `time_axis` 定 0.30 用的是同一条依据：
**取在实测两档之间的空隙，任何落在 0.10–0.16 的值在现有证据下行为相同**。它是可配置常量而非调参结果，
随产物落盘（`method.params.cohesion_lift_min`），将来有第三类语料时据实修订。

巨簇的内聚度（0.819）**只比未分类堆（0.750）高 0.069**——这是"它不是一个主题"的量化说法，
不是"我看着觉得它是大杂烩"。

### 2.4 处理：二次细分为 `analyses[1]`，且子簇必须过同一个检测器

2A 的 schema 早就为这件事留好了位置（`analyses` 是数组、`parent_analysis_id`、`input_scope`）。
**不改主分析的方法与参数**——这一点是对"改全局默认值等于在 n=1 的收益上过拟合"这条批评的正面回应。

```
analyses[0]  input_scope = all_kept_docs          method.name = hdbscan (eom)   ← 完全不变
analyses[1]  input_scope = {kind: "parent_group",
                            analysis_id: "topics-01", group_id: "g01"}
             parent_analysis_id = "topics-01"     method.name = hdbscan (leaf)
```

流程（每一步都可判定，没有"看着办"）：

1. 对 `analyses[0]` 的每个 group 算 `lift`。
2. `lift < 0.12` 的 group 标记为 `under_differentiated`，**它本身不再作为主题呈现**。
3. 对每个被标记的 group，仅在其成员向量上重跑 HDBSCAN（`cluster_selection_method='leaf'`，
   其余参数继承父分析），产出子簇。
4. **子簇逐个过同一个检测器**（基线沿用父分析的 residual）。通过的成为主题；
   不通过的，其成员**折回 residual**，`reason_code = "subdivision_rejected"`。
5. 父 group 的成员中未进入任何通过子簇的，折回 residual，`reason_code = "under_differentiated_parent"`。

> **`analyses[0]` 一个字节都不改。** "折回 residual"指的是这些文档在 `analyses[1]` 里的
> `disposition` 是 `residual`，不是回头去编辑第一轮的结果。2A 合同要求"同时保留第一轮的
> residual 与第二轮的 assigned 两套 disposition"，改写父分析会直接毁掉这条。
>
> 因此 `analyses[1].assignments` **恰好覆盖父 group 的全部成员**（不多不少），
> 而"这次运行实际没有主题的文档"是一个**派生量**：
> `analyses[0] 的 residual` ∪ `analyses[1] 的 residual`。
> 该派生由 §3.3 的公共函数统一给出，下游不各自拼。

实测（Notion g01，509 篇）：细分出 9 个子簇，**9/9 全部通过检测器**（lift +0.165 … +0.242，
与正常簇同档），394 篇折回 residual。人工核验九个子簇全部可一句话命名（样本在仓库外报告）。

净效果：

| | 主题数 | residual |
|---|---|---|
| Apple Notes | 5（不变，无 group 被标记） | 222（77.4%，不变） |
| Notion | 2 → **10** | 243 → 637（84.1%） |

Apple Notes 上**没有任何 group 触发检测器**，因此 2A′ 在该语料上是完全零改动——
这既是选择性验证，也意味着这条改动不会悄悄改掉已经好用的结果。

### 2.5 不做 halo（方案 C），以及为什么这不是在绕过回头条件

- 条件③是 halo 的对症触发器，而它当前 **not_evaluable**（无非本人语料）。
- 拿本人的第二份语料替代"非本人语料"来判定③，正是回头条件想防的自证。
- 因此 halo 保持**未裁决**，`revisit_gate` 里如实记为 `not_evaluable`，
  并写明解除条件：**取得一份非本人来源的语料后重新评估**。

⚠️ 明确记账：细分后 Notion 的 residual 升到 84.1%。若将来在非本人语料上也落在 >70%，③即触发，
处方是 halo。**本 spec 不预先声称"高 residual 是导出语料的固有属性"**——DESIGN §13 已把这个强论断
降级为证据不足，2B 不重新捡起它。

## 3. L2 洞察目录

### 3.1 三族，以及为什么必须分族

洞察分 `topic` / `residual` / `corpus` 三族。分族不是为了好看，是为了堵一个具体的漏洞：

**若所有洞察平等计数，回头条件就会被 corpus 族的统计条目填满而永不触发。**
5 个主题 + 8 条语料统计 = 13 条，"12–20 条凑满了"，于是①永远为假。
这个项目已经有三轮"留一条兜底路径，规则就被它绕过"的事故史（链接层 3–5 审），不能再来一次。

因此：

- **人肉 gate 的 12–20 上限按总条数算**（校对疲劳是按行数发生的）。
- **回头条件①②按 `topic` 族条数判定**。统计条目填不满回头条件。

### 3.2 洞察清单

`topic` 族 — 每个**呈现级** group 一条（见 §3.3）：

| kind | 内容 | 条件 |
|---|---|---|
| `topic_cluster` | 关键词命名 + 篇数 + 占 kept 比例 + 3 篇证据 | 每个通过检测器的 group |

`residual` 族：

| kind | 内容 | 条件 |
|---|---|---|
| `fragment_zone` | X 篇没有形成主题（占 kept Y%） | `residual > 0` |
| `long_orphans` | 碎片区里篇幅最大的 3 篇（纯按长度排序，**不做任何归属**） | `residual ≥ 3` |

> ⚠️ 这条起初写的是「长度进入 kept 前 20% 的文档」，实施时被证伪：**residual 占
> 77–84% 是这类语料的常态**，用全语料分位数时分位点本身就被 residual 主导——
> 阈值取严就恒假、取松就把整个碎片区都说成「长笔记」（两种都实际撞到了）。
> 改成无阈值的排序，既不可能空洞，也不引入魔数。

`corpus` 族：

| kind | 内容 | 条件 |
|---|---|---|
| `retention` | total → kept，空壳丢弃数、重复丢弃数 | 总是 |
| `date_blindness` | 可解析日期占比，**以及三类时间洞察为何不在这份报告里** | `time_axis.available == false` |
| `broken_refs` | 未解析引用数，按"图片/附件 vs 文档"分类 | `unresolved_links > 0` |
| `length_profile` | 篇幅中位数 / 最长 / 不足 N 字的篇数 | 总是 |
| `exact_duplicates` | 内容完全相同被合并的篇数 | `dropped_duplicate > 0` |

条件不成立就**不产出**——绝不输出"你有 0 篇重复文档"这种为了凑数的空洞察（硬不变量 #3）。
两份语料上 `dropped_duplicate` 都是 0，这条正好是条件门的活体测试。

预期条数（实测推算）：

| | topic | residual | corpus | 总计 |
|---|---|---|---|---|
| Apple Notes | 5 | 2 | 4 | **11** |
| Notion（2A′ 后） | 10 | 2 | 4 | **16** |

Apple Notes 落在 11，低于 12。**这不是缺陷，12 不是要靠凑数达到的下限**——
它是人肉 gate 的疲劳上限。①的判据是 topic 族，不是总数。

### 3.3 呈现级 group 的定义（下游唯一该读的那一层）

被细分的父 group **不作为主题呈现**，呈现的是它通过检测器的子簇。规则写死为一句话：

> **呈现级 group = 所有未被标记 `under_differentiated` 的 group，
> 加上所有通过检测器的子簇。**

这条规则由 2B 实现为**两个**公共函数，2C / 2D / 2E 一律调它们，不各自解释 `analyses` 数组
——**否则三个下游会长出三套不一致的解释**：

```python
presentation_groups(index) -> list[GroupRef]   # 有序，顺序即呈现顺序
effective_residual_ids(index) -> list[str]     # 各分析 residual 的并集，去重后排序
```

### 3.4 主题数超限时的截断

若呈现级 group 超过 `TOPIC_INSIGHT_CAP = 12`，按篇数降序取前 12，并**必须**同时给出：

- 总主题数 M 与未列出的 N；
- 未列出主题覆盖的文档数与占 kept 比例；
- 未列出主题的 `group_id` 全量清单（进 `insights.json`，不进 `insights.md` 正文）。

只写"12 个主题"而隐去遗漏，才是制造虚假完整性。截断本身不说谎，隐瞒才说谎。

### 3.5 明确推迟的洞察

| 推迟项 | 理由 | 解除条件 |
|---|---|---|
| 三类时间轴洞察（兴趣迁移 / 半衰期 / 沉默主题） | 两份目标语料 `available=false`，实现了也验证不了 | 出现 `time_axis.available == true` 的目标语料 |
| residual 到最近簇原型的距离洞察（"X 篇贴着主题 T2 的边"） | **这已经是 halo 判断**。不落 membership 字段也仍然制造了软归属 | 随 halo（方案 C）一起裁决 |
| residual 内的近重复成组 | 同上——对 residual 做成组即方案 D 的范围 | 随 D 一起裁决 |

## 4. 簇命名：关键词管线

### 4.1 为什么不能用文档标题

真实语料实测：簇的 medoid 标题分别是一个带 emoji 的缩写、一句招呼语、一个人名加逗号、
一个两字名词——**簇是好的（与 R2 人工验收一致），烂的是标题**。标题因此降级为**证据行**，
不作为名字。

### 4.2 管线

```
正文 → 去 markdown 噪音（代码块 / 图片 / 链接目标 / URL）
     → 混合脚本分词（拉丁按词，CJK 按 2-gram + 3-gram）
     → 类 TF × 语料级 IDF（IDF 在真实文档间算，不在拼接的类文档间算）
     → 过滤（见 4.3）
     → 重叠去重（子串与位移碎片）
     → top-k 关键词
```

**IDF 必须在真实文档层面算**。早期原型把 IDF 算在"每簇拼成一篇"的类文档之间，
结果整簇的停用词因为"只有这一簇是意大利语"而显得极其独特，直接成为簇名。

### 4.3 过滤器

| 过滤器 | 作用 | 治什么 |
|---|---|---|
| 内置通用词表 | 功能词与无领域信号的高频词 | `che` / `non` / `people` / `bene` 当簇名 |
| 簇内文档频率 ≥ `MIN_CLUSTER_DF` | 词至少出现在簇内两篇里 | 单篇偶然词 |
| **lift ≥ `MIN_LIFT`** | 簇内文档占比 ÷ 簇外文档占比 | 跨簇重复的模板词 |
| CJK n-gram 内聚度（PMI） | 出现频率显著高于其字符独立出现的乘积 | 完全由字频解释的伪 n-gram |
| **CJK 左右邻接熵 ≥ `MIN_BOUNDARY_ENTROPY`** | 真词的左右邻居多样，碎片近乎固定 | 边界错位碎片 |
| 重叠去重 | 已选词的子串 / 首尾位移重叠的候选跳过 | `我们这` 与 `们这周` 同时入选 |

**判据用尺度无关的 lift，不用全局文档频率的绝对上限。** 原型先试过 `GLOBAL_DF_CAP`：
它在 757 篇语料上看着能用，其实是在拟合「簇占语料多大比例」——29 篇的簇恰好压在 5% 线下，
换一份语料或换个簇大小就整批失效（在 12 篇的测试语料上把关键词全滤空了）。
lift = 簇内文档占比 ÷ 簇外文档占比，对语料规模与簇大小都不敏感。

**邻接熵是治 CJK 碎片的主力，PMI 不是。** 中文没有词边界，滑窗会切出
`励模型`（奖励模型）、`合人类`（符合人类）这类边界错位的碎片——它们的字都不是功能词，
词表和 PMI 都拦不住，但它们的左邻居几乎恒定。这是无监督分词的经典判据，无依赖、确定、
语言无关。

⚠️ **PMI 的分母必须同源**：n-gram 的概率只能在**同长度 n-gram 的总数**里算。
早期实现拿「全部 token 数」（含 2-gram + 3-gram + 拉丁词）作分母、却拿 CJK 字符数
算字符概率，两个概率空间不可比，PMI 被系统性压低，把 `推敲`、`造型` 这种真词也滤掉了。

全部常量随产物落盘（`insights.json` 的 `naming.params`），产物不隐瞒名字是怎么来的。

### 4.4 已知失效模式（不假装解决）

**单一语言独占一个簇时，该语言的功能词会被判为区分性关键词。** 实测意大利语簇与英语簇
都出现过整组功能词命名。管线补一份**内置的多语言功能词表**（覆盖 en / it / zh 常见功能词
与 CJK 黏着字），能挡住实测到的大部分情况，但**它按定义覆盖不了没收录的语言**。

产品层面的应对，按 DESIGN §4.2 的设计本来就在：

1. 关键词**永远与 3 篇证据标题、篇数同时呈现**——人一眼能判断名字对不对；
2. 名字不对就**取消勾选**，这正是人肉 gate 的职责；
3. 2E 的 L3 可以用用户自己的 key 重新命名。

**产物不得把关键词说成"主题名"**。`insights.md` 的措辞是"这 32 篇里最具区分度的词是 …"，
不是"你的主题是 …"。措辞差别不是文案偏好，是硬不变量 #4。

### 4.5 验收线

在两份真实语料上，**呈现级 group 中至少 70% 的关键词组能被人判定为"认得出是这个主题"**。
这与 2A"至少 3 个簇能被一句话命名"是同一条人工验收线，不进 CI。
实测基线记录在仓库外报告里，spec 只记结论与复现命令。

## 5. `insights.json` 合同

```json
{
  "schema_version": "0.1",
  "run_id": "…",
  "corpus_hash": "…",
  "index_schema_version": "0.1",
  "versions": {"kb_init": "…", "python": "…", "sklearn": "…"},
  "naming": {
    "method": "ctfidf_multiscript",
    "params": {"top_k": 4, "min_lift": 2.0, "min_cluster_df": 2,
               "cjk_pmi_min_bigram": 2.0,
               "stoplist": "bundled-v1"}
  },
  "presentation": {
    "group_refs": [{"analysis_id": "topics-01", "group_id": "g02"},
                   {"analysis_id": "topics-02", "group_id": "g01s03"}],
    "truncated": {"shown": 12, "total": 14, "omitted_group_refs": [], "omitted_docs": 0}
  },
  "counts": {"topic": 10, "residual": 2, "corpus": 4, "total": 16},
  "revisit_gate": { "…见 §7…" },
  "insights": [
    {
      "insight_id": "T1",
      "family": "topic",
      "kind": "topic_cluster",
      "payload": {
        "group_ref": {"analysis_id": "topics-02", "group_id": "g01s03"},
        "keywords": ["…", "…", "…"],
        "doc_count": 29,
        "share_of_kept": 0.0383,
        "evidence_doc_ids": ["…", "…", "…"]
      },
      "canonical_text": "…",
      "evidence": {"doc_ids": ["…"], "stat": null},
      "claude_md": {"section": "focus_areas"}
    },
    {
      "insight_id": "C1",
      "family": "corpus",
      "kind": "retention",
      "payload": {"total": 1925, "kept": 757, "dropped_stub": 1168, "dropped_duplicate": 0},
      "canonical_text": "…",
      "evidence": {"doc_ids": [], "stat": {"total": 1925, "kept": 757}},
      "claude_md": null
    }
  ]
}
```

### 合同条款

- **`payload` 与 `canonical_text` 双载，且必须等价。** `canonical_text` 是 `payload` 的
  **已验证物化快照**：生成时与读取时都校验 `render(payload) == canonical_text`，不等即 fail closed。
  只存 `payload`、每次现渲染是不行的——渲染器一升级，`compile` 就会编译出**用户从没审过的文字**，
  而人肉 gate 的全部价值就在于"用户审过的正是最终进入 CLAUDE.md 的那句话"。
- **身份是 `(run_id, insight_id)`。** `insight_id` 只在单次 run 内稳定，不做跨 run 的内容哈希 ID——
  内容哈希只是指纹，证据变化时反而会制造"这是同一条洞察"的假象。跨 run 的保护由 fail closed 提供。
- **`claude_md` 显式声明去向。** `null` 表示这条洞察只进 Wrapped，不进档案线。
  语料层统计（留存率 / 断链数）对 agent 无用，进 CLAUDE.md 只是噪音。
  2D 据此路由，不自己猜哪条该进。
- **`evidence` 分型而非统一 doc 列表。** topic 族挂 `doc_ids`，corpus 族挂 `stat`。
  强行让统计类洞察挂 222 个 doc_id 既无意义也撑爆文件。
- **`presentation.group_refs` 是有序的**，顺序即呈现顺序，下游不得自行重排。
- **`counts` 必须由 `insights` 数组派生**，不独立计数（沿用 2A `coverage` 的同一条纪律：
  独立计数迟早漂移，而漂移没有症状）。
- **group 引用一律是 `(analysis_id, group_id)` 二元组**，沿用 2A 的约定。
- **`corpus_hash` / `run_id` 取自 `index.json`**，与 manifest 不符即 fail closed。

## 6. `insights.md` 合同

```markdown
# kb-init — 洞察确认清单

<!-- kb-init:run_id=… corpus_hash=… schema_version=0.1 -->
> 只改 `[x]` / `[ ]`。改正文不会生效——`compile` 按 ID 从 insights.json 取正文。
> 改完跑 `kb-init compile`，或先跑 `kb-init validate insights.md` 单独校验。

## 主题（10 条）

- [x] `T1` 这 29 篇里最具区分度的词是 … — 占 kept 3.8%
      证据：〈标题一〉·〈标题二〉·〈标题三〉

## 碎片区（2 条）

- [x] `R1` 637 篇没有形成主题（占 kept 84.1%）

## 语料（4 条）

- [x] `C1` 读入 1925 篇，留下 757 篇；1168 篇是空壳
```

- **短 ID 可见**（`T1` / `R1` / `C1`），不用隐藏标记——看得见反而不容易误改。
- **头部 `run_id` / `corpus_hash` 写在 HTML 注释里**：它必须在文件内，否则用户把两次运行的
  `insights.md` 和 `insights.json` 配错时无从发现。用户改坏它 → 校验失败 → fail closed，
  这正是想要的行为。
- **`validate` 的失败一律带行号**，且**绝不静默少编几条**：缺失 / 重复 / 未知 ID /
  跨 run / 跨 corpus / 头部损坏，全部 fail closed。
- 解析器只认 `- [x]` / `- [ ]` 加反引号包裹的 ID。正文一律忽略（因为不信任）。

## 7. `revisit_gate`

回头条件的判定落在 `insights.json` **顶层**，不混进 `insights` 数组——它不是给用户勾选的洞察，
是给项目自己留的收据。

```json
"revisit_gate": {
  "rules_version": "2b-1",
  "inputs": {"topic_insight_count": 10, "presentation_group_count": 10,
             "residual_share": 0.841, "corpus_is_first_party": true},
  "conditions": [
    {"id": "insufficient_topics",  "threshold": 4,    "observed": 10,
     "state": "not_triggered", "prescription": "subdivide"},
    {"id": "topics_concentrated",  "threshold": 2,    "observed": 10,
     "state": "not_triggered", "prescription": "subdivide"},
    {"id": "residual_high",        "threshold": 0.70, "observed": 0.841,
     "state": "not_evaluable",  "prescription": "halo",
     "reason": "requires_third_party_corpus"}
  ]
}
```

**`insufficient_topics` 的阈值 4 的依据**：DESIGN §6 要求 CLAUDE.md 的「关注领域」
**按稳定性排序**——少于 4 个领域时排序不产生任何信息，那一节就退化成一个列表。
所以 4 是"这个产品字段还成立吗"的下限，不是聚类质量的下限。它刻意**不取在 5**
（Apple Notes 的实测值）：把阈值定在正好让现状通过的位置，等于给现状背书，
是"断言恒真"的近亲。

- **三态**：`triggered` / `not_triggered` / `not_evaluable`。
  没有非本人语料就是 `not_evaluable`，不许拿本人的第二份语料冒充它通过。
- **2B 只供数，不自授裁决权**：`revisit_gate` 里的 `state` 由一个纯函数按 `rules_version`
  记录的规则算出，是可复现的收据；**触发不改变任何运行时行为**，它只是让下一次人类决策有据可依。
- `prescription` 记录的是 §2.2 那张修正后的映射，避免"条件→处方"的错配再次发生。

## 8. 架构

| 模块 | 职责 | 依赖 | 不认识 |
|---|---|---|---|
| `subdivide.py` | 内聚度检测器 + 过大簇二次细分（2A′） | numpy, sklearn | 文本、洞察、写盘 |
| `keywords.py` | 混合脚本关键词抽取（纯函数：文本 + 分组 → 词） | sklearn | 索引结构、洞察、写盘 |
| `insights.py` | 读回索引 → 三族洞察 → `InsightSet`；`presentation_groups()` | 上二者 | 渲染、写盘 |
| `insights_md.py` | `insights.md` 的**唯一**真源：渲染 + 解析 + 校验 | 无 | 索引、聚类 |
| `index.py`（改） | 新增 `read_index()` 公共读取器（含 `.npy` 完整性校验） | numpy | — |

沿用 Plan 1 / 2A 的约定：**每一层的写盘集中在一处**。索引产物（含 2A′ 追加的
`analyses[1]`）仍然只由 `index.py` 写；洞察产物只由 `insights.py` 写。
`subdivide.py` 与 `keywords.py` 都不碰磁盘。

**`insights_md.py` 必须同时承担渲染与解析。** 分成两个模块、由两个人各写一半，
是格式漂移最经典的来源；同一个模块里 round-trip 测试才拦得住。

### 8.1 数据来源：写盘后读回

洞察生成**不吃内存里的 index 对象**，而是从 staging 里读回 `index.json` + `index-vectors.npy`，
走公共 `read_index()`（校验 `.npy` 的 shape / dtype / 有限性与 `assignments` 一致，
即 2A spec §6 对读取方的要求）。

理由：这条路径能抓到序列化、映射与版本边界上的问题，而 2C / 2D / 2E 走的正是这条路。
额外 I/O 可忽略。**如果只有内存路径被测过，那三个下游第一次读文件时才会发现合同没兑现。**

### 8.2 流水线位置

```
… → 索引阶段（2A，写 index.json + .npy 进 staging）
  → 2A′ 细分（若有 group 触发检测器，追加 analyses[1] 并重写 index.json）
  → 洞察阶段（读回 → 生成 → 写 insights.json + insights.md 进 staging）
  → 写 manifest（含 index_status / insights_status）
  → 一次 rename ← commit 点
```

2A′ 在索引子事务**内部**完成（细分失败 = 索引失败，回滚整个索引子事务），
因为它改的是 `index.json` 本身，不能出现"索引写了一半又被追加改坏"的中间态。

## 9. 错误处理

### 9.1 退出码 6

洞察层失败（索引成功）→ **新增退出码 6**，不拓宽 5 的语义。

5 与 6 的**恢复动作不同**：5 意味着索引没做成（重跑需要网络 / 模型），
6 意味着索引好好的、只有洞察层挂了。拓宽 5 会让既有脚本在只需重算洞察时错误地重跑整个索引。

### 9.2 失败模式表

| 失败模式 | 行为 | 退出码 |
|---|---|---|
| `index_status != complete` | 洞察层不运行，`insights_status = "skipped"`，reason `no_index` / `index_failed` | 沿用 0 / 5 |
| 读回 `index.json` 失败或与 manifest 的 `corpus_hash` 不符 | **fail closed**，`insights_status = "failed"`，reason `contract_violation` | 6 |
| `.npy` 完整性校验不过（shape / dtype / NaN） | 同上，reason `contract_violation` | 6 |
| 关键词抽取抛错 | `insights_status = "failed"`，reason `naming_failed` | 6 |
| `render(payload) != canonical_text` | **fail closed**，reason `contract_violation`——绝不写出一份自相矛盾的产物 | 6 |
| 写 `insights.json` 或 `insights.md` 失败 | 回滚洞察子事务（两个文件要么都在要么都不在），发布清洗产物与索引 | 6 |
| 2A′ 细分抛错 | 属于索引子事务，回滚整个索引 | 5 |
| 呈现级 group 为 0（全 residual） | **不是错误**：topic 族 0 条，residual + corpus 族照常产出 | 0 |
| kept 为 0 | **不是错误**：照常写一份合法的空 `insights.json` 与只有头部的 `insights.md` | 0 |
| `--no-index` | 洞察层不运行，`insights_status = "skipped"`，reason `no_index` | 0 |
| `KeyboardInterrupt` / `SystemExit` | 不吸收、不伪装成部分成功 | 130 / 透传 |

`insights_reason` 是稳定枚举：`no_index` / `index_failed` / `contract_violation` /
`naming_failed` / `io_failed`。

**洞察是一个子事务**：`insights.json` 与 `insights.md` 要么都发布，要么都不发布。
只有 md 没有 json，用户会对着一份永远 `validate` 不过的清单勾选。

## 10. 测试策略

沿用 2A 的三层网，并针对"断言可能恒真"这条教训逐条设计。

**第一层：无模型的 fake 单测**（秒级，进 CI）

| 层 | 测什么 |
|---|---|
| `subdivide.py` | lift 计算的数学正确性；构造一个"两个远离的团被并成一簇"的向量集，断言它被标记且细分出两个通过检测器的子簇；构造一个紧密簇断言**不**被标记（防止检测器把所有簇都判为过大） |
| `keywords.py` | 停用词被滤掉；CJK 位移碎片被 PMI 挡掉；子串与位移重叠去重；**同输入同输出**；空簇 / 单文档簇不抛异常 |
| `insights.py` | 条件门：`dropped_duplicate=0` 时**不产出**该条洞察；`residual=0` 时不产出碎片区；`counts` 由数组派生且自洽；截断时 `omitted` 记账完整 |
| `insights_md.py` | **round-trip**：渲染 → 解析 → 勾选状态与 ID 集合完全还原；用户改正文不影响解析；改坏头部 / 重复 ID / 未知 ID / 缺 ID 全部 fail closed **且报出行号** |
| 契约 | `render(payload) == canonical_text` 对每一条洞察成立 |
| pipeline | 故障注入：分别在写 json 前、写 md 前抛错，断言最终只有两种状态——两个文件都在，或都不在 |
| 真实语料（skipif） | 两份语料跑通；Apple 上**无 group 被标记为 under_differentiated**；Notion 上恰有一个被标记且细分后主题数 ≥ 8 |

**关于"断言恒真"的具体防范**（这个项目为此付过一次代价）：

- "每条 topic 洞察的证据 doc_id 都属于该 group" —— 若证据为空则恒真。
  **必须同时断言证据非空且数量等于预期**。
- "关键词都出现在簇内文档里" —— 若关键词列表为空则恒真。
  **必须同时断言关键词数量等于 `top_k`（簇够大时）**。
- "细分后的子簇都通过检测器" —— 若一个子簇都没产生则恒真。
  **必须同时断言子簇数 ≥ 2**。
- 检测器测试必须**同时包含正例与负例**：只测"巨簇被标记"而不测"正常簇不被标记"，
  一个恒返回 `True` 的检测器也能全绿。

**第二层：真实语料验收**（不进常规 CI）
两份语料的完整跑通已在 §2 / §3.2 给出预期数字，实施后逐条核对；
关键词质量按 §4.5 人工验收，结果记在仓库外报告。

**第三层：确定性**
同一份 `index.json` → 逐字节相同的 `insights.json`（`run_id` 取自索引，不新生成）。
关键词打分相等时按词本身排序破平；洞察顺序 canonical。

## 11. 验收标准

1. 全量测试通过；第一层不下载模型、秒级跑完。
2. 同一份 `index.json` 跑两次，`insights.json` 逐字节相同。
3. Apple Notes：无 group 被标记，5 条 topic 洞察，总条数落在 10–13。
4. Notion：恰一个 group 被标记，细分后 topic 洞察 ≥ 8，`revisit_gate` 中
   `topics_concentrated` 为 `not_triggered`、`residual_high` 为 `not_evaluable`。
5. `insights.md` round-trip 无损；改坏头部 / ID 时 `validate` fail closed 并报行号。
6. 索引失败时不产出任何洞察文件且退出码仍为 5；洞察失败时索引产物完整、退出码 6。
7. 人工验收：呈现级 group 中 ≥70% 的关键词组能被认出是什么主题。
8. Codex 终审判定可合并。

## 12. 对既有文档的变更项

1. **README 退出码表**：新增 6。
2. **README**：新增 `insights.json` / `insights.md` 两个产物与 `kb-init validate` 子命令。
3. **manifest**：新增 `insights_status`（`complete` / `failed` / `skipped`）与 `insights_reason`。
4. **2A spec §2.1**：回头条件的处方映射修正为 §2.2 的表（①②→细分，③→halo），
   并注明③在当前语料上 `not_evaluable`。
5. **DESIGN §5**：注明 L2 在导出类语料上的重心是主题而非轨迹，三类时间洞察按 §3.5 推迟。
6. **STATUS.md**：记录回头条件②已触发与 2A′ 的处置。

## 13. 风险

| 风险 | 处理 |
|---|---|
| 检测器阈值 0.12 在第三类语料上不适用 | 阈值随产物落盘可复现；判据是"相对本语料 residual 基线"而非绝对值，已比篇数比例稳健 |
| 细分把真实存在的上位主题打碎 | 子簇逐个过同一检测器；父簇与子簇的 lift 都记进产物，事后可判 |
| 单语言簇的功能词命名 | §4.4 已如实记为已知失效模式；证据行 + 人肉 gate + L3 重命名三重兜底 |
| 关键词管线的常量是在两份语料上定的 | 全部随产物落盘；两份语料都是本人的，这一点在 `revisit_gate` 里如实记账 |
| 2A′ 扩大了 2A 的范围 | 由回头条件强制触发，非自选动作；作为独立 commit 先落，可单独回退 |
