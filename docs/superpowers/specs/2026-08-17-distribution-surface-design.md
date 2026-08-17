# 发布面（分发、平台支持、首跑体验）— 设计 spec

> 状态：设计已定，待 Codex 架构审 → 实现
> 相关：DESIGN §7（载体与分发决策）/ §9 R14 R15 R10 / §10（v0.1 验收标准）
> 前置裁决（2026-08-17，贾老师）：**项目名沿用 `kb-init`** / **协议 Apache-2.0** /
> **这一轮只本地备齐，不建公开仓库、不发 PyPI**

## 1. 这一轮解决什么

三样东西目前是空的：**没有 LICENSE、没有 CI、`pyproject` 缺发布元数据**。
后果不是"不好看"，是两条已记录的风险**根本无法被检验**：

- **R15（跨平台 wheel）** 被 Codex 判为「真正的分发风险，不是 uv 本身」——而在没有
  任何平台矩阵的情况下，我们只在一台 macOS arm64 上跑过；
- **R14（首次运行不是秒开）** 的处方写着「首次运行体验按一等公民设计
  （进度 / 预估时间 / 模型下载可见）」——**这一条从来没有实现**。

## 2. 开工前的实测：两个改变结论的发现

### 2.1 R14 的钩子在，但没有人接

`embed.py` 的适配器早就带了 `progress` 回调（会发 `model_loading` 事件），
但 `pipeline.py` 与 `cli.py` **从未接过它**。实测跑一次真实语料，用户在整个索引
阶段看到的是**一片空白**——冷启动那次还要下载 ~90MB 模型、按分钟计。

R14 的处方不是"没做好"，是"没做"。

### 2.2 R15 的第一项**做不到**，不是没验

查 PyPI 的实际 wheel 清单（不是推断）：

| 依赖 | Windows x64 | macOS Intel | macOS arm64 | Linux x64 |
|---|---|---|---|---|
| numpy / scikit-learn / PyYAML / tokenizers | ✅ | ✅ | ✅ | ✅ |
| fastembed / huggingface-hub | 纯 Python（`py3-none-any`） | — | — | — |
| **onnxruntime** | ✅ `win_amd64` | **❌ 一个都没有** | ✅ 但只有 `macosx_14_0_arm64` | ✅ 但只有 `manylinux_2_28` |

`onnxruntime` **至少从 1.18 起就不再发 macOS x86_64 wheel**（逐版本查过
1.18 / 1.19.2 / 1.20 / 1.22 / 1.28，全都没有）。

**所以 R15 的原文要改**：它写的是「发布前 CI 必须验 Windows x64 / macOS Intel +
Apple Silicon / Linux x64」，而 macOS Intel 这一项不是「CI 还没验」，是**装不上**
——再多 CI 也变不出一个不存在的 wheel。

由此得到真实的支持面，**必须如实写进 README 与 classifiers**：

| 平台 | 结论 |
|---|---|
| Windows x64 / arm64 | 支持 |
| Linux x64 / aarch64 | 支持，**要求 glibc ≥ 2.28**（manylinux_2_28） |
| macOS Apple Silicon | 支持，**要求 macOS ≥ 14** |
| **macOS Intel** | **不支持**，且不是我们能修的 |

> ⚠️ 这不是"降低标准"。**声称支持一个装不上的平台才是产物撒谎**（硬不变量 #4）。
> 一个 Intel Mac 用户按 README 跑一条命令，得到的会是一大段 onnxruntime 编译失败
> ——那比一开始就告诉他不支持糟糕得多。

## 3. 明确的边界：这一轮不建仓库、不发包

贾老师已裁决只本地备齐。因此：

- **不写任何指向尚不存在的 URL。** `pyproject` 的 `[project.urls]` 与 README 的徽章
  一律**留空**，直到仓库真的建起来。写一个 404 的链接是产物撒谎的最省事版本。
- CI 配置**写好但跑不了**（它要在 GitHub 上才跑）。这一点必须在 STATUS 里如实记账：
  **R15 只被"依赖侧"证据覆盖，"构建侧"仍未验证**——两者不是一回事。
- 能在本地验的那部分**必须真验**（§5 的打包冒烟），不拿"写好了 CI"冒充"验过了"。

## 4. R14：首跑体验

### 4.1 判据

不是"加个进度条"，而是回答一个问题：**用户盯着一个没有任何输出的终端，
要不要怀疑它挂了？**

现状：索引阶段静默，冷启动可达数分钟。这一条足以让人 Ctrl-C。

### 4.2 做什么

把 `embed.py` 已有的 `progress` 回调接到 CLI，按阶段输出到 **stderr**
（stdout 留给结果，管道友好）：

```
读入 620 篇，保留 287 篇…              ← 已有
正在准备模型（首次运行需下载约 90MB，按分钟计）…   ← 新增，模型加载前
正在计算向量 400/1130…                  ← 新增，节流输出
正在聚类…                              ← 新增
```

三条硬约束：

1. **非 TTY 时降级**：不刷屏、不发 `\r`。CI 日志与 `2>` 重定向里都得能看。
2. **节流**：按条数间隔发，不是每篇一行。
3. **不猜时间**：只说"按分钟计"这种已知事实，**不报预估剩余时间**——
   我们没有可靠的估计依据，编一个进度百分比就是产物在撒谎。
   R14 处方里的"预估时间"据此降级为"预先告知量级"。

### 4.3 不做

| 不做 | 理由 |
|---|---|
| 进度条 / `\r` 覆盖式刷新 | 需要判断终端能力，且在日志里变成一堆控制字符 |
| 剩余时间预估 | 没有可靠依据，是猜（硬不变量 #3） |
| `--quiet` / `--verbose` 开关 | v0.1 不需要两套；有需要时 `2>/dev/null` 就够 |

## 5. 本地能验的必须真验：打包冒烟

CI 跑不了不等于什么都验不了。这一轮**必须**跑通并留下证据：

1. `uv build` 产出 wheel 与 sdist；
2. 把 wheel 装进一个**全新的临时环境**（不是开发环境）；
3. 在那个环境里跑 `kb-init --version` / `kb-init --help`；
4. 在那个环境里跑一次 `--no-index` 的真实小语料，确认产物出来。

第 2 步是关键：开发环境里 `kb-init` 能跑，证明不了**打出来的包**能跑——
`[tool.hatch.build.targets.wheel]` 少配一处，装出来就是空的，而开发环境完全看不出。

## 6. 变更清单

| 文件 | 变更 |
|---|---|
| `LICENSE`（新） | Apache-2.0 全文 |
| `NOTICE`（新） | Apache-2.0 的归档声明（一行版权） |
| `pyproject.toml` | license / authors / readme / keywords / classifiers（含如实的 OS 与 Python 分类）；**不加 urls** |
| `.github/workflows/ci.yml`（新） | 平台矩阵按 §2.2 的**真实**支持面写：ubuntu-latest / windows-latest / macos-14，Python 3.12+ |
| `src/kb_init/embed.py` | 无需改（钩子已在） |
| `src/kb_init/pipeline.py` | 把 progress 回调透传给适配器 |
| `src/kb_init/cli.py` | 提供 progress 消费者，按 §4.2 输出到 stderr |
| `README.md` | 新增「支持的平台」；首跑预期；不加徽章 |
| `docs/DESIGN.md` | R15 改写为"依赖侧已验、构建侧待 CI；macOS Intel 判定为不支持"；R14 处方里的"预估时间"降级为"预先告知量级"；R10 记为已裁决（沿用 kb-init） |
| `STATUS.md` | 记账：CI 未跑过、PyPI 未发、仓库未公开 |

## 7. 测试策略

| 测试名 | 断言 |
|---|---|
| `test_progress_reports_model_stage_before_embedding` | 模型加载事件先于任何向量事件到达消费者 |
| `test_progress_is_throttled` | 1000 篇只产出个位数条输出行（不是每篇一行） |
| `test_progress_goes_to_stderr_not_stdout` | stdout 只有结果行；进度全在 stderr（管道友好） |
| `test_progress_has_no_carriage_returns` | 输出里不含 `\r`（日志与重定向里可读） |
| `test_progress_never_claims_remaining_time` | 输出里不出现"剩余""预计还要"这类字样（**不猜**） |
| `test_no_index_run_emits_no_model_progress` | `--no-index` 不该说"正在准备模型"——它根本不加载模型 |
| `test_pipeline_runs_without_a_progress_consumer` | 不传 progress 时一切照常（回调是可选的，不能变成必需依赖） |

**打包冒烟**（§5）不进 pytest：它要建临时环境、装 wheel，属于发布前的人工检查项，
写进 README 的开发者段落并在 STATUS 记录本轮的执行结果。

## 8. 验收标准

1. 上表测试全绿，全量 `pytest -q` 不退步（当前 488 passed + 6 smoke）；
2. `uv build` → 全新环境装 wheel → `kb-init --help` 与一次 `--no-index` 跑通，**留下输出证据**；
3. 冷启动路径上，用户在**开始下载模型之前**就看得到一句说明；
4. README 的「支持的平台」与 §2.2 的实测表一致，**不含任何未验证的平台声明**；
5. 仓库里没有任何指向不存在地址的链接。

## 9. 风险

| 风险 | 处置 |
|---|---|
| CI 写了却从没跑过，给人"已经验过"的错觉 | STATUS 与 DESIGN 双处记账：**构建侧未验证**。这是这一轮唯一的空头支票，必须写明 |
| 进度输出污染程序化调用 | 全部走 stderr；`test_progress_goes_to_stderr_not_stdout` 是它的牙齿 |
| macOS Intel 用户仍会来试 | README 明写不支持；这是我们能做的全部 |
| Apache-2.0 的 NOTICE 维护成本 | 只放一行版权，不列第三方——依赖的协议由包管理器解决，我们不做二次分发 |
