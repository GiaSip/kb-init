# STATUS — kb-init

> 最后更新：2026-08-14（终审通过，Plan 1 已合并 main）

## 当前阶段

**Plan 1 全部完成并合并入 main。** 共 6 轮 Codex 5.6-Sol 终审迭代，第 6 轮裁定「可以合并」。
测试 93 passed；真实 Notion 语料（1925 篇）内部链接死链 2/237，剩余 2 条为已知的嵌套结构链接。
下一步是 Plan 2（洞察层 L2/L3 + Wrapped + CLAUDE.md 编译）。

原始阶段记录： 这是"系统开源第一块"计划的落地项目——目标是扩大在 Agent 领域的影响力。

## 最近进展

- 2026-08-13 完成需求收敛，7 轮讨论定完全部核心分叉，设计文档 `docs/DESIGN.md` v0.1 落盘
- 关键收敛路径：Memory vs KB 三层拆分 → 冷启动是真痛点 → 载体定为独立 CLI → 从结构诊断转向内容洞察 → 双输出（Wrapped + CLAUDE.md）确立验收闭环
- 竞品检索确认三块空位：冷启动批量导入 / 内容洞察 L2-L3 / CLAUDE.md 生成
- **B 段（KB 管线打包）已砍**：`AgriciDaniel/claude-obsidian` 10.8k★ 已占且更完整
- 实测地面真值已获取（`probes/kb_doctor_probe.py`）：Notion 导出 1925 篇 60% 空壳，Apple Notes 620→242 留存 39%

- 2026-08-13 Codex 5.6-Sol 工程 review 完成（commit `0f411d3`）：裁决 R2/R9，抓到流水线顺序真 bug，补 §4.3 IR 合同，新增 R11–R15

## 卡住的

无阻塞项。

- **R14 已定案**（2026-08-13 贾老师拍板）：v0.1 只走 `uvx`，**不同时维护两套实现**；宣传语不吹"零安装"，改为"装好 uv 后一条命令运行，无需自己装 Python"；首次运行体验按一等公民设计（进度 / 预估时间 / 模型下载可见）；GitHub Releases 单二进制列入 **v0.2 明确路线**

## 下一步

1. ~~验证 R1~~ ✅ 2026-08-13 完成，clone 源码逐条核实，三条断言全部成立（见 DESIGN §2.3）
2. ~~走 writing-plans~~ ✅ Plan 1（核心管线，10 任务）已出：`docs/superpowers/plans/2026-08-13-core-pipeline.md`
3. **执行 Plan 1** ← 当前。Plan 2（洞察与编译）待 Plan 1 完成后再写
4. Plan 2 实施前先在 `Archive/Apple Notes` 上验 bge-small-zh 的真实聚类质量（R2 剩余部分）

## 语料资产（已在手）

| 用途 | 路径 |
|---|---|
| 主校准集（烂语料，60% 空壳） | `~/Documents/notion-export/Export-1b76b367-.../` |
| 副校准集（40% 空壳） | `~/Documents/Obsidian Vault/Archive/Apple Notes` |
| 处理后配对样本（验证编译效果） | `~/Documents/Obsidian Vault/Personal/*/Apple Notes/` |
| 优等生对照组 | `~/Documents/Obsidian Vault/Wiki/` |
| 当年的转换脚本（参考） | `~/Documents/assistant-output/notion_to_obsidian.py` |


## 阻断项修复轮（2026-08-13）

Codex 5.6-Sol 全分支终审判定「暂不合并」，6 条阻断项 + 5 条必修 minor 已全部处理：

| 项 | 状态 |
|---|---|
| B1 路径冻结逐篇而非全局 | ✅ emit 重构为两遍式 + 引用映射 + unresolved 记账 |
| B2 文件系统等价名碰撞 | ✅ 入口 NFC+casefold 检测记账 / 出口等价键唯一化 |
| B3 目录输入无总量限制 | ✅ 累计 .md 字节执行 max_total_bytes |
| B4 单文件原子≠整次运行原子 | ✅ staging 目录整体发布 |
| B5 文件名注入 frontmatter | ✅ 改用 yaml.safe_dump |
| B6 CLI 无错误边界 | ✅ 退出码合同 0/1/2/3/4，不吐 traceback |
| 5 条必修 minor | ✅ null byte / 超大文件静默跳过 / frontmatter 炸弹 / 年份回归 / .md.tmp 残骸 |

**最关键的发现**：B1 修完后合成测试全绿，但真实语料 288 条内部链接 **100% 死链**——
Notion 导出用的是 URL 编码的标准相对链接而非 wikilink，只处理 wikilink 会漏掉全部真实链接。
补 `_rewrite_md_links` 后降到 2/227（0.9%，均为嵌套结构链接）。
> ⚠️ 这个「2/227」后来被证明是低估——当时的计数漏掉了文件名含 `#` 的一整类。
> 同口径复量的真实基线是 15/240，见下一节。
**合成语料测不出真实形态，这是这一轮最贵的教训。**

测试 67 → 78 passed。

## 链接层终审收口（2026-08-14，第 4–6 轮）

前三轮修完仍有一条「活着的错链」：`_rewrite_md_links` 没有当前文档的目录上下文。
四审、五审各又抓出同一家族的绕过路径，六审裁定可合并。三轮改动都在 `emit.py` 一个文件里：

| 轮 | 问题 | 修法 |
|---|---|---|
| 3 审遗留 | 标准相对链接按 basename/stem 跨目录兜底 | 新建 `by_path` 索引，`_LinkIndex` 把「名字语义」(wikilink) 与「路径语义」(标准链接) 分成两张表 |
| 4 审 | 「当前目录不中就退回导出根」仍在猜基准 | 删掉根回退，链接基准唯一 = 当前文档所在目录（CommonMark） |
| 4 审 | `--wikilinks` 整体跳过解析，歧义作废失效、slug 化输出名点不开 | 方言模式同样先解析，只改输出语法 |
| 4 审 | 文件名含 `#` 时被当锚点切掉 | 按每个 `#` 位置枚举候选，由 `by_path` 实际命中裁决 |
| 5 审 | 精确别名已判歧义，剥 `.md` 回退又把它解析掉 | 别名解析改三态 `_resolve_alias → (name, ambiguous)`，歧义即停 |

**贯穿这三轮的同一个教训**：每一条都是「解析不到就再换一种猜法」的变体。
只要还留着一条兜底路径，「歧义不猜」就会被它绕过——而错链不像死链，不会有人来报。

真实语料上的净效果：Notion 内部链接死链 15 → 2（剩余 2 条是嵌套结构链接，已记入 README 已知限制）。
其中 11 条来自一类此前从未被计入的缺陷：文件名含 `#`。**旧账面「死链 2/227」是低估**——
当时那把尺子漏数了这一类。测试 80 → 93 passed。

## 下一步

**Plan 2**（洞察层 L2/L3 + Wrapped + CLAUDE.md 编译）。实施前先在 `Archive/Apple Notes`
上验 bge-small-zh 的真实聚类质量（R2 剩余部分）。
