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

## 卡住的

无阻塞项。两个待裁决项（不影响开工）：
- R2 本地 embedding 的中文质量方案
- R9 语言/分发选型（Python+uv vs Node+npx），取决于 R2

## 下一步

1. **Codex 工程 review** `docs/DESIGN.md`，重点裁决 R2 + R9
2. 真装一遍 claude-obsidian 验证 R1（"它没有 X"目前只来自 README fetch）
3. review 通过后走 writing-plans 出实施计划

## 语料资产（已在手）

| 用途 | 路径 |
|---|---|
| 主校准集（烂语料，60% 空壳） | `~/Documents/notion-export/Export-1b76b367-.../` |
| 副校准集（40% 空壳） | `~/Documents/Obsidian Vault/Archive/Apple Notes` |
| 处理后配对样本（验证编译效果） | `~/Documents/Obsidian Vault/Personal/*/Apple Notes/` |
| 优等生对照组 | `~/Documents/Obsidian Vault/Wiki/` |
| 当年的转换脚本（参考） | `~/Documents/assistant-output/notion_to_obsidian.py` |
