# STATUS — kb-init

> 最后更新：2026-08-13

## 当前阶段

**设计定稿，未开工。** 这是"系统开源第一块"计划的落地项目——目标是扩大在 Agent 领域的影响力。

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
2. **走 writing-plans 出实施计划** ← 当前
3. 实施前先在 `Archive/Apple Notes` 上验 bge-small-zh 的真实聚类质量（R2 剩余部分）

## 语料资产（已在手）

| 用途 | 路径 |
|---|---|
| 主校准集（烂语料，60% 空壳） | `~/Documents/notion-export/Export-1b76b367-.../` |
| 副校准集（40% 空壳） | `~/Documents/Obsidian Vault/Archive/Apple Notes` |
| 处理后配对样本（验证编译效果） | `~/Documents/Obsidian Vault/Personal/*/Apple Notes/` |
| 优等生对照组 | `~/Documents/Obsidian Vault/Wiki/` |
| 当年的转换脚本（参考） | `~/Documents/assistant-output/notion_to_obsidian.py` |
