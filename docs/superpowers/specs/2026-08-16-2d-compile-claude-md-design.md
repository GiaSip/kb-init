# 2D `compile` → CLAUDE.md — 设计 spec

> 状态：设计已定，待 Codex 架构审 → 实现
> 上游：2B spec §5（`insights.json` 合同）/ §6（`insights.md` 合同）/ §7（`revisit_gate`）
> 相关：DESIGN §4.2（Wrapped 是档案的验收界面）/ §4.3（IR 合同）/ §6（CLAUDE.md 产出什么）

## 1. 这是什么

`kb-init compile <insights.md>` —— 读勾选状态，按 ID 从 `insights.json` 取正文，
产出**用户知识库的 `CLAUDE.md`**。

> ⚠️ 命名歧义先说清楚：**这里产出的 `CLAUDE.md` 是给用户的 agent 读的档案**，
> 与本仓库根目录那份 `CLAUDE.md`（kb-init 自己的项目上下文）是两个东西。
> 本文档里凡指前者，一律写「档案」。

2D 是 DESIGN §4.2 那个闭环的**档案渲染**那一支。裁决权归它（§4.1）：档案错了，
agent 会带着错误的自我认知一直走下去，且很难被发现。

## 2. 开工前的实测：先看实物，再裁分叉

STATUS 的「头号分叉」写着三条路，倾向③但**无证据**。所以先拿两份真实语料的
topic 洞察压成档案看实物（产物在仓库外：`~/Documents/assistant-output/kb-init-r2/2d-mock-*.md`）。
实物推翻了分叉本身的前提，三条发现：

### 2.1 不是「五节填得出两节」，是**一节**

两份 `insights.json` 里所有非 `null` 的 `claude_md` 全部是 `{"section": "focus_areas"}`
——**2B 没有产出任何指向「领域词汇表」的洞察**。要出第二节，2D 只能自己从
`T1…Tn` 的 `keywords` 重新汇总一份词汇表。那会同时撞两条已裁决的纪律：

- 2B spec §5 合同：「2D 据此路由，**不自己猜**哪条该进」；
- 人肉 gate 的存在理由：用户在 `insights.md` 上审的是「这 29 篇里最具区分度的词是 …」，
  进档案的却变成「你的术语表：design, architecture …」——**用户从没审过后面那句**。

所以「先发两节」在今天不是一个可选项，它是一个**未实现的上游功能**。

### 2.2 §6 的「关注领域」按它自己的定义就填不出来

DESIGN §6 写的是「关注领域 — 按**稳定性**排序（跨时间反复出现），不是按数量」。
而 `time_axis.available == false`（两份语料日期可解析率 5.2% / 6.3%），
稳定性无从算起，只能按篇数排。**照抄 §6 的措辞就是产物撒谎**（硬不变量 #4）。
本 spec 据此把 §6 的这一条降级为：按篇数排序，并在节内静态导语里如实写明排序依据。

### 2.3 覆盖率缺口：档案只解释了六分之一的语料

| 语料 | 主题数 | 主题覆盖 | residual |
|---|---|---|---|
| Notion（kept 757） | 10 | 120 篇 = **15.9%** | 84.1% |
| Apple Notes（kept 287） | 5 | 65 篇 = **22.6%** | 77.4% |

而 `R1 fragment_zone`（「X 篇没有形成主题」）目前 `claude_md=None`，不进档案线。
于是档案会说「这是你的关注领域」而绝口不提另外那 84%——agent 会当成全集。
这是硬不变量 #4 在 2D 上的一个真实缺口，**必须堵**。

### 2.4 顺带记账：Apple Notes 那份门面拿不出手

实物的前两条分别是**一整组意大利语功能词**和**一组无领域信号的英语高频词**
（具体词见仓库外报告，不进仓库）。这正是 2B spec §4.4 已声明的失效模式
（单语言簇出该语言通用词），**不在 2D 重新调参**。它的后果记在 §11 验收里。

## 3. 裁决：2D 是**纯管道**

**节数由上游有多少料决定，2D 不含任何「这条该进哪一节」的知识，也不合成内容。**

- 今天 = 2 节（`focus_areas` + 新增的 `coverage`，见 §8）；
- 2B 若补一条 vocabulary 洞察 → 自动 3 节；
- 2E 接上 → 自动 5 节。**2D 一行都不用改。**

代价说清楚：**v0.1 的门面产物就是两节**。这是诚实的代价，不是缺陷——
用五节的标题装两节的料，才是缺陷。

## 4. 档案的输出合同

### 4.1 长什么样

```markdown
# 关于这个知识库

<!-- kb-init:claude_md run_id=… corpus_hash=… schema_version=0.1 -->
<!-- 由 kb-init compile 生成，来自用户逐条确认过的洞察清单。 -->

## 关注领域

> 按篇数排序。

- 这 29 篇里最具区分度的词是 〈词一〉 · 〈词二〉 · 〈词三〉 · 〈词四〉 — 占 kept 3.8%
  证据：〈标题一〉·〈标题二〉·〈标题三〉

## 这份档案的覆盖范围

- 637 篇没有形成主题（占 kept 84.1%）
```

> 那两行 HTML 注释是**给人看的出处说明**，**不是覆盖授权的依据**——授权走
> `compile.json` 回执 + 内容哈希（§5.2）。初稿曾拿这行标记当授权，那等于把钥匙
> 印在门上。

### 4.2 正文一律是 `canonical_text` 原句，2D 不重新措辞

这是本 spec 最容易被「为了好看」绕过的一条，所以把理由写死：

2B spec §5 的双载合同要防的是「**渲染器一升级，compile 就编译出用户从没审过的文字**」。
如果 2D 拿 `payload` 自己排一句更好看的话（比如把关键词加粗、把「这 29 篇里最具区分度的词是」
改写成「你关注 …」），那么 **2D 的渲染器升级会犯一模一样的病**——只是把病从 2B 挪到了 2D。

因此：

- 档案的每一条 = `- {canonical_text}`，**逐字**；
- 证据行 = `payload.evidence_titles` 的原始字符串（用户在 `insights.md` 上看到的正是它们），
  只做空白折叠，不改写；
- 2D 可以加**结构**（标题、列表符号、分节顺序）与**静态常量导语**，
  但导语必须是与 `payload` 无关的固定文本。任何随数据变化的措辞都属于「重新措辞」。

**已知代价**：`canonical_text` 是为审阅写的句子（「这 29 篇里最具区分度的词是 …」），
放进档案读起来像审阅清单而不像档案。这个代价是自愿付的——
让档案好看的唯一合法路径是**让 2B 改 `canonical_text` 本身**（那句话会同时出现在
`insights.md` 上被用户审），不是让 2D 另起一个渲染器。

### 4.3 `SECTIONS` 表：section → 这一节长什么样

表放在 `claude_md.py`（档案线自己的排版知识），不放 `insights.py`（那会让洞察层
知道档案长什么样，层次反了），也不放 `insights.json`（排版不进真源）。

```python
SECTIONS = (
    ("focus_areas", "关注领域", "按篇数排序。"),
    ("coverage", "这份档案的覆盖范围", None),
)
```

导语是**静态常量**，不含任何从 `payload` 派生的数字或措辞（§4.2）。

> ⚠️ **静态常量也可能撒谎**（Codex 审 #7）。初稿的导语写的是「这不是『稳定性』排序——
> 这份语料里能确定时间的文档太少，算不出稳定性」。后半句是**关于这份语料的事实**，
> 却被硬编码成了常量：换一份 `time_axis.available == true` 的语料，这句话立刻变成假话。
> 判据收紧为：**导语只能陈述对任何语料都成立的管道事实**（「按篇数排序」由
> `presentation_groups()` 的定义保证恒真）。要陈述语料事实，就必须走洞察 + 人肉 gate，
> 不能走常量。

- **元组有序，顺序即输出顺序。**
- 节内条目顺序 = `insights.json` 的数组顺序，**2D 不重排**（沿用 2B「`group_refs` 有序，
  下游不得自行重排」的同一条纪律）。

**未知 section 一律 fail closed，绝不静默跳过。** 2E 接上时若新增
`section: "blind_spots"` 而表里没有对应项，`compile` 必须报错退出、**不写文件**。
「认不出就不输出」是硬不变量 #1 的第六种形态：上游新增一节，下游默默不输出，
而这种事**没有症状**——没人会来报「我的档案少了一节」，因为没人知道本该有。

## 5. 数据流与 gate 序列

```
kb-init compile <out_dir>/insights.md
  1. knowledge/ 必须已存在、是目录、且不是符号链接（**第一个 gate**）        → 否则 4
  2. 定位同目录的 insights.json / manifest.json；manifest gate：
     insights_status == "complete"                                          → 否则 7
  3. 读 insights.json（读不动 / 顶层不是对象 / 缺必需键）                       → 否则 9
  4. 版本 gate：payload.schema_version == 本版 insights.SCHEMA_VERSION        → 否则 9
  5. 身份 gate：payload 的 run_id / corpus_hash 是非空字符串，且与 manifest 一致 → 否则 9
     （只比相等不够：两边同时缺失时 None == None 会放行，那是拿缺失当共识）
  6. 结构 gate（**全量，与勾选状态无关**，见 §5.1）                            → 否则 9
  7. validate_markdown(md, payload)                                          → 不合法则 7
  8. parse_markdown(md) → selections
  9. 过滤：selections[id] is True 且 claude_md is not None
 10. canonical_text 校验：进档案的每一条 render(payload) == canonical_text     → 否则 9
 11. 可进档案的条目 == 0                                                      → 8，不写文件
 12. 取锁 <out_dir>/.kb-init-compile.lock（O_EXCL）                          → 已被占用则 4
 13. 覆盖授权（§5.2）                                                        → 未获授权则 1
 14. 渲染 → 原子落盘 knowledge/CLAUDE.md → 写回执 compile.json → 释放锁
```

**第 2 步不是可选的。** `validate` 命令已经确立了「读取入口必须先问 manifest」
（2B 五审的裁决）。compile 是第二个读取入口，放行就等于两个入口两套标准。

**第 4、5 步必须早于第 7 步**（Codex 审 #4）。`validate_markdown` 比对的是 `insights.md`
头部与 `insights.json` 的三个字段——若 json 本身是旧版或来自另一次运行，它会报出
「你手上这份清单不合法」（7），把用户支去改一份没有问题的文件。**json 的自洽性
必须先于清单的合法性判定**：7 的修复动作在用户手上，9 的在工具手上，报错码指错了方向，
用户就会做错事。

**第 5 步是新加的**（Codex 审 #2）。原设计只让 manifest 回答「洞察算不算数」，
却从不核对它与 json 是不是同一次运行的产物。`manifest.json` 顶层本来就带
`run_id` 与 `corpus_hash`（已核实），不核对等于白放着一份现成的交叉证据。

**第 10 步只校验要进档案的那几条**，不是全部。这不是兜底：它校验的正是产物要用的每一句话。
corpus 族的文案与档案无关，让它挡住用户是无谓的严格。

### 5.1 结构 gate：为什么必须在过滤**之前**

原设计把「未知 section」的判定放在分组阶段，也就是**过滤之后**——于是一条
`section: "blind_spots"` 的洞察只要**没被勾选**，就会安静地流过全部检查
（Codex 审 #3、#5）。后果有两层：第一，2E 接上时新增的一节，只要用户没勾就永远不会
报错，直到某天他勾了才炸；第二，若那恰好是**唯一**能进档案的一族，管道会走到
「可归档条目 == 0」，报出退出码 8「你一条都没勾」——**而真正的原因是工具不认识它**。
用一个错误码把用户支去改一份没有问题的清单，正是硬不变量 #1 的第七种形态。

因此结构 gate 扫**全部** `insights`，与勾选无关，任一条不合格即 9：

| 检查 | 不合格的样子 |
|---|---|
| `insight_id` 唯一 | 两条同 ID → 一个勾选框授权两段正文进档案（Codex 审 #5） |
| 必需键齐备 | 缺 `payload` / `canonical_text` / `family` / `kind` |
| `claude_md` 形状 | 既不是 `None` 也不是 `{"section": str}`：缺 `section` 键、值为 `null` / 空串 / 非字符串、含多余键 |
| `section` 值已知 | 不在 `SECTIONS` 表里 |

**「形状对但值不认识」与「形状本身就坏」都进 9**，不分两个码：两者的修复动作相同
（用当前版本重跑），分开只会让退出码表变长而不增加信息。

### 5.2 覆盖授权：回执 + 内容哈希，不是一个可复制的标记

初稿的判据是「文件首部含 `<!-- kb-init:claude_md run_id=… -->` 且 run_id 一致就允许替换」。
Codex 审 #1 指出这是**可伪造的授权**：那行标记就在产物里明晃晃写着，
用户复制到自己的笔记里、或反过来手工编辑过我们自己写的档案，两种情况都会被静默覆盖——
**而覆盖的是用户的原始数据**。

改成三重判据，全部满足才授权替换：

1. `<out_dir>/compile.json` 回执存在，且其 `run_id` 与本次一致；
2. 现存档案文件的 **sha256 等于回执里记的那个**（我们上次写下去时是什么样，现在还是什么样）；
3. 目标路径**不是符号链接**——绝不跟随符号链接写，那能把任意路径变成写入目标。

任何一条不满足 → **退出码 1，拒绝覆盖**，诊断里说清是哪一种（没有回执 / 不是这次运行 /
文件被改过 / 是符号链接）。哈希这一条顺带解决了初稿没想到的情形：**用户手工改过档案**——
那是他的编辑，不该被我们无声抹掉。

TOCTOU 与并发（Codex 审 #1）：

- 新建路径用 `O_CREAT | O_EXCL`，「检查时不存在」与「写入时创建」是同一个原子动作；
- 整个 compile 持有 `<out_dir>/.kb-init-compile.lock`（同样 `O_EXCL` 创建，`finally` 删除）。
  已被占用 → 退出码 4，诊断给出锁文件路径。**不做超时自动清锁**——
  「等久了就当它死了」是典型的兜底路径，而残锁的正确处置是人看一眼再删。

**仍然不提供 `--force`**（§7）。删掉那个文件是一个明确、可见、可撤销的动作；
一个开关不是。

### 5.3 写盘失败与「不带走已完成的产物」

顺序：**tmp 先写满 → 作废旧回执 → 原子替换档案 → 写新回执**。两个文件做不到共同原子，
所以选一条能守住的不变量：**回执存在 ⇒ 它描述的就是盘上那份档案。**

- 档案写失败 → 旧档案原样保留，退出码 4；
- 档案写成功、回执写失败 → **档案保留**（硬不变量 #2），无回执，退出码 4，
  诊断明说「档案已写入但回执没落盘，下次 compile 会拒绝覆盖它——
  删掉 `knowledge/CLAUDE.md` 再重跑」。

> ⚠️ 三审 R3-1：二审的修法把「作废回执」放在了**写 tmp 之前**，于是磁盘满这种
> 常见故障会留下 {旧档案完好, 回执没了}——下次 compile 以「没有回执」拒绝覆盖，
> 要求用户删掉一份**完好的、我们自己写的**档案。修一个撒谎的回执，修出了一个
> 冤枉用户的诊断。tmp 写满之后再作废，失败窗口就只剩 `os.replace` 本身。
>
> ⚠️ 初稿是「先档案后回执」且不作废旧回执，Codex 二审 B3 指出重编译时的后果：
> 档案换成了新的、回执还记着旧哈希——下一次 compile 会比对哈希后**指控用户
> 手改过档案**，而其实是我们自己换的。一份描述着不存在内容的回执就是在撒谎
> （硬不变量 #4），宁可没有。代价是「档案写失败」时连旧回执也没了，
> 下次会以「没有回执」拒绝覆盖——诚实且 fail closed，可接受。

**`knowledge/` 不存在时不创建，直接退出码 4**——这一条与 Codex 审 #6 的建议相反，
理由记在这里：能走到 compile，说明 `insights_status == "complete"`，也就说明流水线
跑完过、`knowledge/` 本来就该在。它不在，意味着有人删了或移了目录。此时创建一个
只装着一份 `CLAUDE.md`、没有任何知识的 `knowledge/`，是在造一个**撒谎的产物**
（硬不变量 #4）——它看起来像一个知识库，其实是空的。报错让人去看发生了什么，更诚实。

### 5.4 为什么输出到 `knowledge/` 而不是 `<out_dir>/` 顶层

`knowledge/` 才是用户当作知识库（vault）打开、交给 agent 的目录；顶层放的全是元数据
（`index.json` / `insights.json` / `manifest.json`）。档案放顶层，agent 根本读不到它。

回执 `compile.json` 走相反的判据：它是元数据，放**顶层**，与 `manifest.json` 并列。
把它放进 `knowledge/` 会往用户的知识库里塞一份不是知识的文件。

## 6. 退出码

沿用现有 0–7，新增两个。**分开的判据是「下一步动作不同」**（README 已确立）：

| 码 | 含义 | 下一步 |
|---|---|---|
| 8 | 清单合法，但**没有任何条目能进档案线** | 回去勾几条，或接上 2E 供料 |
| 9 | `insights.json` 与本版代码不一致（schema / 身份 / 结构 / 未知 section / `canonical_text`） | 用当前版本重跑一次索引与洞察 |

8 与 9 不能合并：8 的修复在用户手上（改勾选），9 的修复在工具手上（重跑）。
**而这正是 §5.1 那条排序纪律的价值**——结构 gate 若晚于过滤，一个本该报 9 的情形
会伪装成 8，把用户支去改一份没有问题的清单。

复用而不新增的两个：

- **1**（拒绝覆盖）——沿用「输出冲突」的现有语义，覆盖授权失败的四种情形共用它，
  靠诊断文案区分；
- **4**（读写失败）——新增三种情形共用：`knowledge/` 缺失或不可写、锁被占用、
  回执写失败。它们的下一步动作对**调用方脚本**是同一个（停下来报人看），
  只对人不同；退出码分裂的判据是前者，不是后者。

## 7. 明确不做

| 不做 | 理由 |
|---|---|
| 从 `keywords` 合成「领域词汇表」 | §2.1：2D 不自己猜哪条该进，也不产用户没审过的文字 |
| 给档案的每一节加「共 N 条」之类的汇总 | 那是 2D 自己产的内容，且会与勾选状态不一致 |
| `--force` 覆盖 | §5.2 |
| 修 Apple Notes 的关键词命名质量 | 2B spec §4.4 已记为已知失效模式，不在 2D 对着这两份语料调参 |
| 把 `revisit_gate` 写进档案 | 它是给项目自己的收据，不是给 agent 的知识 |

## 8. 对 2B 的一处改动

`R1 fragment_zone` 的 `claude_md`：`None` → `{"section": "coverage"}`。

**只改这一个字段**，`canonical_text` / `payload` / 渲染器一律不动。理由是 §2.3 的覆盖率缺口：
让「另外 84% 没形成主题」这句诚实声明走**和主题完全同一条路**——同样进 `insights.md`
让用户勾、同样用 `canonical_text`、同样由 2D 路由。2D 不需要为它加任何特例。

需要同步改的：`tests/test_insights.py::test_corpus_insights_never_route_to_claude_md`
断言的是 corpus 族（不涉及 R1），**不受影响**；但要新增一条断言 R1 路由去向的测试，
否则这个字段被改回去不会有任何症状。

`R2 long_orphans` 保持 `None`：「篇幅最大的 3 篇还没长成主题」是给人看的线索，
对 agent 的自我认知没有用。

**尾巴记明**：用户可以取消勾选 R1，档案于是又不提覆盖率了。这**不算产物撒谎**——
人肉 gate 的职责就是用户说了算，而取消勾选是一个显式动作。

## 9. 架构

| 模块 | 职责 | 依赖 | 不认识 |
|---|---|---|---|
| `claude_md.py` | `SECTIONS` 表 + 结构 gate + 档案渲染（纯函数）+ 覆盖授权与写盘 | `insights.render`（只为校验 `canonical_text`） | 索引、聚类、CLI |
| `cli.py`（改） | `compile` 子命令：编排 §5 的 gate 序列、映射退出码 | `insights_md` / `insights` / `claude_md` | 渲染细节 |
| `insights.py`（改） | R1 的 `claude_md` 字段（§8） | — | — |

沿用项目约定：**每一层的写盘集中在一处**。档案与回执只由 `claude_md.py` 写。

模块内的函数边界（纯函数与副作用分开，纯函数部分才好测）：

```python
check_structure(payload) -> None                    # §5.1，不合格即抛
select_for_archive(payload, selections) -> list     # 过滤 + 分节，纯函数
render_archive(payload, grouped) -> str             # 逐字 canonical_text，纯函数
publish(out_dir, run_id, text) -> None              # 授权 + O_EXCL + 原子替换 + 回执
```

`compile` 的 CLI 形态与 `validate` 对称（`kb-init compile <insights.md>`），
复用 `main()` 里那条「恰好两个参数且第二个是已存在的文件」的特判——不引入 subparsers，
那会弄坏 `kb-init <source>` 的位置参数用法（现有测试专盯这个）。

## 10. 测试策略

**每一条检测器都配负例**（硬不变量：只测「坏的被抓住」，恒真的实现也能全绿）。

| 测试名 | 断言 |
|---|---|
| `test_unchecked_items_are_excluded` | `- [ ]` 的条目不进档案 |
| `test_null_claude_md_never_enters_archive` | corpus 族（`claude_md=None`）不进档案，即使勾着 |
| `test_r1_routes_to_coverage_section` | R1 进 `coverage` 节（§8 的守卫） |
| `test_body_is_canonical_text_verbatim` | 档案里的那一行**逐字**等于 `canonical_text` |
| `test_unknown_section_fails_closed` | 未知 section → 退出码 9 且**文件未被创建** |
| `test_unknown_section_fails_even_when_unchecked` | **未勾选**的未知 section 同样 → 9（§5.1 的核心守卫） |
| `test_known_sections_still_render` | 负例的配对正例：恒抛错的实现过不了这条 |
| `test_malformed_claude_md_shapes_fail_closed` | 参数化：`{}` / `{"section": None}` / `{"section": ""}` / `{"section": 7}` / `{"section":"x","extra":1}` 各自 → 9 |
| `test_duplicate_insight_id_fails_closed` | json 里两条同 ID → 9 |
| `test_identity_mismatch_with_manifest_fails_closed` | manifest 的 `run_id` / `corpus_hash` 与 json 不符 → 9 |
| `test_stale_json_reports_9_not_7` | 旧 schema 的 json + 匹配它的 md → **9 而不是 7**（顺序纪律的守卫） |
| `test_canonical_text_mismatch_fails_closed` | 篡改 `canonical_text` → 9，不写文件 |
| `test_schema_version_mismatch_fails_closed` | json schema 与本版不符 → 9 |
| `test_zero_archivable_items_writes_nothing` | 全不勾 → 8，且目标文件不存在 |
| `test_manifest_gate_four_states` | 缺失 / 损坏 / 无该字段 / 顶层非对象，四种都拒绝（与 `validate` 同标准） |
| `test_rerun_replaces_own_output` | 回执 + 哈希 + 非符号链接三条都满足 → 原子替换 |
| `test_refuses_to_overwrite_foreign_file` | 无回执的同名文件（模拟一篇真叫 CLAUDE.md 的笔记）→ 1，**内容逐字未变** |
| `test_refuses_to_overwrite_other_run` | 回执 run_id 不同 → 1 |
| `test_refuses_when_archive_hand_edited` | 回执在、run_id 对，但文件哈希对不上（用户改过）→ 1，**内容未变** |
| `test_forged_marker_does_not_authorize` | 把 `<!-- kb-init:claude_md … -->` 复制进一篇真笔记、无回执 → 1（Codex 审 #1 的守卫） |
| `test_refuses_symlink_target` | 目标是符号链接 → 1，**链接指向的文件内容未变** |
| `test_lock_blocks_concurrent_compile` | 锁文件已存在 → 4，且档案未被改动 |
| `test_missing_knowledge_dir_is_error_not_created` | `knowledge/` 不存在 → 4，且**不创建该目录** |
| `test_receipt_write_failure_keeps_archive` | 回执写失败 → 4，但档案仍在（硬不变量 #2） |
| `test_section_and_item_order_follows_json` | 节序按 `SECTIONS`，条目序按 json 数组，不重排 |
| `test_atomic_write_leaves_no_tmp` | 写盘失败不留 `.tmp` 残骸，锁也被释放 |

**真实语料验收**（不进 CI，语料不在则跳过）：两份语料各跑一遍完整链路
（`kb-init` → 手动勾选 → `compile`），产物落仓库外。

**fixture 纪律**：合成 `insights.json` 时不要造成「每条都长得一样」的规整数据——
2B 踩过「太规整的合成语料把好实现判成坏的」。fixture 至少要有：多语言关键词、
含空白与换行的证据标题、空 `evidence_titles` 的条目。

## 11. 验收标准

**合同层**（自动）：

1. 上表全部通过，全量 `pytest -q` 不退步（当前 299 passed + 4 smoke）；
2. 产物里不含本机绝对路径、不含 `<out_dir>` 之外的任何路径；
3. 每一条输出都逐字等于它的 `canonical_text`。

**门面层**（人肉，这一条是 STATUS 点名要加的）：

4. **拿两份真实语料的产物给贾老师看，他能说「这个可以发出去」。**
   四天 86 个 commit 之后 README 承诺的两样门面产物一个都没有；2D 的完成定义
   必须包含「这东西能拿出去给人看」，不能只验合同对不对。
5. 已知会不达标的部分**提前记账，不当作阻断项**：Apple Notes 那份的前两条是
   已声明的命名失效模式（§2.4）。若贾老师判定它拿不出去，处置是**2E 重命名**，
   不是回到 2B 调参——对着这两份语料调参已经是过拟合。

## 12. 风险

| 风险 | 处置 |
|---|---|
| 档案读起来像审阅清单（§4.2 的自愿代价） | 记账，不在 2D 解决。要好看就改 2B 的 `canonical_text`，让它同时是好审的句子和好读的句子 |
| 两节的门面撑不起传播 | 这是 2E 的题，不是 2D 的。2D 的价值是把管道打通：2E 一接上，五节自动出现 |
| `SECTIONS` 表与上游 section 值漂移 | 三条测试合起来才是防线：未知 section 抛错 + **未勾选也抛错** + 已知 section 正常渲染的配对正例 |
| 用户取消勾 R1 → 档案又不提覆盖率 | §8 尾巴：显式动作，不算撒谎 |
| 残锁需要人工删除 | 记账。自动清锁需要一个「多久算死」的阈值，那是魔数 + 兜底路径两样一起来 |

## 13. Codex 架构审记录（2026-08-16，spec 阶段，read-only + xhigh）

7 条阻断，**全部成立**，无一误报。6 条照办，1 条采用不同处置：

| # | 问题 | 处置 |
|---|---|---|
| 1 | 覆盖授权只凭一个**印在产物里的可复制标记**；符号链接 / TOCTOU / 并发均可损坏真实笔记 | 改为回执 + 内容哈希 + 拒绝符号链接 + `O_EXCL` + 锁（§5.2） |
| 2 | manifest 从不与 json 核对 `run_id` / `corpus_hash`，可能编译另一次运行的陈旧数据 | 新增身份 gate（§5 第 5 步） |
| 3 | 路由校验晚于选择过滤 → 未勾选的未知 section 有静默通道，且会**误报为退出码 8** | 结构 gate 提前到过滤之前、扫全量（§5.1） |
| 4 | 版本 gate 晚于 `validate_markdown` → 旧 json 会被报成 7（清单不合法），把用户支去改一份没问题的文件 | 调序：3/4/5 全部前置于 7 |
| 5 | 未约束 `insight_id` 唯一性 → 一个勾选框可能授权两段正文 | 进结构 gate |
| 6 | I/O 失败与目录异常未规定是否保留既有产物 | 定为 §5.3。**但 `knowledge/` 缺失不采纳「应创建」的建议**——理由见 §5.3：创建一个只装档案、没有知识的 `knowledge/` 是造一个撒谎的产物 |
| 7 | 「静态导语」里塞了**关于这份语料的事实**（日期太少算不出稳定性），换一份语料即成假话 | 导语收紧为只能陈述对任何语料恒真的管道事实（§4.3） |

第 7 条最值得记：它是「产物不许撒谎」的一个新变种——**撒谎不一定来自动态渲染，
写死的常量同样会撒谎**，因为常量陈述的是一个会变的事实。
