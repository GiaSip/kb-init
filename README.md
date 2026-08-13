# kb-init

把你攒了几年、自己都没再打开过的笔记导出，编译成一份干净的、你的 AI agent 能直接用的知识库。

## 安装与运行

需要先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。装好 uv 后一条命令运行，**无需自己安装 Python**：

```bash
uvx kb-init ~/Downloads/notion-export -o my-kb
```

> 首次运行会下载 Python 与依赖，可能需要几分钟。这不是"零安装"，是"零项目安装"。

## 它做了什么

在真实语料上的实测：

| 输入 | 读入 | 保留 |
|---|---|---|
| Notion 导出 | 1925 篇 | 757 篇（39%） |
| Apple Notes | 620 篇 | 287 篇（46%） |

被丢弃的记录**不会消失**——它们连同丢弃原因一起留在 `manifest.json` 里。

## 输出

```
my-kb/
├── knowledge/        干净的标准 Markdown（默认相对路径链接，不绑定 Obsidian）
└── manifest.json     每篇文档的完整状态、身份、日期来源与去向
```
