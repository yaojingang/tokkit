# TokKit

[English](README.md) | [简体中文](README.zh-CN.md)

[产品简介](docs/PRODUCT_BRIEF.md) | [Positioning & roadmap](docs/POSITIONING_AND_ROADMAP.md) | [定位与路线图（简体中文）](docs/POSITIONING_AND_ROADMAP.zh-CN.md)

TokKit 是一个轻量化、本地优先的 AI 编码工具使用量台账。

它解决的是一个很实际的问题：**我在各种 AI 编码工具上到底消耗了多少
token，成本主要花在哪里？** TokKit 会扫描本地工具日志、官方导出文件、
可选的运行时 capture 文件或本地代理记录，然后把这些碎片化 usage 统一
写入本地 SQLite 台账，最后按日期、模型、终端、客户端、来源、token
方向和预估成本生成报表。

日常使用建议直接用 `tok`。更底层的 CLI 是 `tokkit`。`tokstat` 作为旧版
兼容别名保留。

## 示例

以下示例使用同一份合成演示数据：基于原报告 5 倍放大，并增强
Claude Code Opus 4.6 / 4.7 的消耗占比。

[打开交互式 HTML 示例报告](docs/assets/tokkit-demo-5x-claude-opus.html)

TUI 风格示例仪表盘：

![TokKit TUI demo screenshot](docs/assets/tokkit-tui-demo-5x-claude-opus.svg)

CLI 报表：

![TokKit CLI demo screenshot](docs/assets/tokkit-cli-demo-5x-claude-opus.svg)

## 为什么需要 TokKit

AI 编码工作现在经常分散在桌面应用、终端 agent、IDE 插件、本地代理、
官方导出文件和供应商后台里。同一个开发者一周内可能同时使用 Codex、
Claude Code、Warp、Cursor、Augment、CodeBuddy、Trae、ChatGPT 和
GitHub Copilot。

问题是 usage 数据非常分散：

- 有的工具在本地 JSONL 日志里暴露精确 token。
- 有的工具只有会话总量或 credits。
- 有的工具需要官方导出或 API 报表。
- 有的工具只能根据本地缓存文本做估算。
- 供应商后台通常无法统一解释终端、客户端和模型维度的消耗。

TokKit 的目标是把这些碎片整合成一份本地总账。它不会假装所有数字都同样
精确，而是给每条记录保留统计方法：

- `exact`：上游日志或响应里有明确 token 字段。
- `partial`：能拿到有用总量，但缺少某些维度。
- `estimated`：TokKit 根据本地缓存文本或元数据重建出来的估算。

这样既能看趋势和结构，也不会隐藏不确定性。

## 工作逻辑

TokKit 的核心流程是本地优先的数据管道：

1. **发现来源**：查找已知本地日志、会话文件、官方导出文件、capture 文件
   和可选代理记录。
2. **增量扫描**：首次可以全量扫描所有已配置来源；后续扫描复用 checkpoint
   和活跃目标规划，让常用报表保持较快速度。
3. **归一化记录**：把所有 usage 写入 `~/.tokkit/usage.sqlite`，统一记录
   source、app、model、terminal/client 线索、token 字段、method、时间和
   metadata。
4. **本地估价**：使用内置价格表和可选的 `~/.tokkit/pricing.json` 覆盖文件
   计算 `Est.$`。
5. **生成报表**：输出终端表格、JSON、客户端覆盖率、预算视图和静态交互式
   HTML 仪表盘。

本地生成物：

- SQLite 台账：`~/.tokkit/usage.sqlite`
- HTML 和文本报表：`~/.tokkit/reports/`
- 日志和扫描状态：`~/.tokkit/logs/` 及相关状态文件
- Augment 运行时 capture：`~/.tokkit/augment-usage.ndjson`

如果机器上已经存在旧版 `~/.tokstat` 目录，TokKit 会尽量保持兼容。

## 亮点

- 多个 AI 编码工具统一到一个本地台账。
- 默认不需要托管后台，数据留在本机。
- 明确区分 `exact`、`partial` 和 `estimated`，不混淆精度。
- 支持按日期、来源、终端、客户端、模型、Prompt、Output、Cached Prompt、
  Reasoning、Unsplit、预估美元、Credits、Records 聚合。
- 交互式 HTML 报告默认简体中文，支持英文切换、置顶导航、时间范围切换、
  模型筛选和图表 tooltip。
- 增量扫描和活跃目标规划，让重复统计更快。
- 内置模型价格表，并支持本地价格覆盖。
- 支持今天、最近 7 天和本月累计预算检查。
- `tok doctor` 和 `tok setup` 提供本地诊断与引导式配置。
- macOS 可选 `launchd` 自动扫描和自动日报。
- Augment 支持历史本地估算，也支持对新请求做运行时精确 capture。
- 支持 JSON 输出，方便脚本和后续分析。

## 支持的数据来源

当前各来源的行为：

- **Codex Desktop / Codex CLI**：从本地日志精确统计 Prompt、Output、
  Cached Prompt 和 Reasoning tokens。
- **Claude Code**：从本地 Claude session JSONL 精确统计，并识别可检测到的
  VS Code 入口。
- **Warp**：从本地会话/账户数据做 partial 统计，保留可用的 vendor credits。
- **Kaku Assistant**：通过 TokKit 的 OpenAI-compatible 本地代理转发时，如果
  上游响应带 OpenAI 风格 `usage`，可以精确统计。
- **Augment**：根据本地 request selection context 和 checkpoint diff 估算
  历史 usage；安装本地 VS Code 扩展 capture hook 后，可精确捕获新请求。
- **ChatGPT export**：根据官方导出的会话文本做估算。
- **GitHub Copilot usage metrics**：从官方 usage metrics 导出或 GitHub API
  报表做 partial 统计；当报表里包含 Copilot CLI token 总量时可以导入。
- **Cursor**：根据本地 sentry telemetry 事件做估算。
- **CodeBuddy**：根据本地任务历史文本做估算。
- **Trae**：如果本地 `ui_messages.json` 带有 `tokensIn` 和 `tokensOut`，可以
  精确导入对应任务 usage。

## 下载与安装

TokKit 目前位于本仓库的 `tools/tokkit` 目录。

### 方式一：克隆仓库并 editable 安装

这是推荐的本地使用和开发安装方式：

```bash
git clone https://github.com/yaojingang/yao-cli-tools.git
cd yao-cli-tools/tools/tokkit
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

### 方式二：直接从 GitHub 安装

如果你只想安装命令，不想保留工作区：

```bash
python3 -m pip install "git+https://github.com/yaojingang/yao-cli-tools.git#subdirectory=tools/tokkit"
```

### 安装后的命令

- `tok`：日常操作入口
- `tokkit`：底层 CLI
- `tokstat`：兼容旧命令

要求：

- Python 3.10+
- 当前最适合 macOS 本地桌面环境
- 只有扫描 GitHub Copilot API 报表时才需要 `gh`

## 快速开始

安装完成后：

```bash
tok help
tok setup
tok doctor
tok today
tok last 7
tok html month
```

常见首次扫描：

```bash
tok scan codex
tok scan claude-code
tok scan augment
tok scan chatgpt ~/Downloads/chatgpt-export.zip
tok scan copilot --org your-org
tok scan trae
tok scan all
```

`tok scan all` 首次会从所有已知来源 bootstrap。后续 TokKit 会优先扫描最近
活跃的目标，让重复统计更快。如果需要重新全量规划，可以加 `--full`：

```bash
tok scan all --full
```

## 日常使用

可读报表：

```bash
tok today
tok yesterday
tok 2026-05-03
tok week
tok month
tok last 14
```

客户端覆盖率：

```bash
tok clients today
tok clients week
tok clients month
tok clients last 30
```

JSON 输出：

```bash
tok json today
tok json last 7
tok json clients month
```

HTML 报告：

```bash
tok html
tok html week
tok html last 14
tok html month
tok html open
```

HTML 报告会生成在 `~/.tokkit/reports/`，是静态文件，可以本地打开、作为
artifact 分享，或用于演示。普通报表或扫描命令每天首次执行时，也会自动静默生成一份
最近 30 天 HTML 报告；手动执行 `tok html` 会立即重新生成。

自动 HTML 报告可以通过环境变量调整：

```bash
TOK_AUTO_HTML_REPORT=0 tok today
TOK_AUTO_HTML_LAST_DAYS=7 tok today
```

- `TOK_AUTO_HTML_REPORT=0`：关闭每日首次自动生成。
- `TOK_AUTO_HTML_LAST_DAYS=7`：把自动报告窗口改为最近 7 天，默认是 30 天。

报表目录辅助命令：

```bash
tok files
tok open
```

## 底层 CLI 命令

`tok` 是更方便的操作入口，底层仍然可以直接使用 `tokkit`：

```bash
tokkit scan-all --timezone Asia/Shanghai
tokkit report-daily --date today --timezone Asia/Shanghai
tokkit report-range --last 7 --timezone Asia/Shanghai
tokkit report-clients --last 30 --timezone Asia/Shanghai
tokkit report-html --last 30 --open
tokkit serve-proxy --host 127.0.0.1 --port 8765 --upstream-base-url https://api.example.com/v1
```

## 报表字段说明

核心字段：

- `Total`：当前行的总 token。
- `Prompt`：输入/提示词 token；如果上游把缓存上下文也计入 input，这里也会
  包含 Cached Prompt。
- `Output`：模型生成输出 token。
- `Cached Prompt`：命中缓存的 Prompt token。
- `Reasoning`：供应商暴露的 reasoning token。
- `Unsplit`：只能拿到总量、无法安全拆成 Prompt/Output 的 token。
- `Est.$`：基于模型价格、Prompt、Cached Prompt 和 Output 本地估算的 API
  成本；OpenAI 的 cached tokens 通常包含在 input 内，Claude/Anthropic 的
  cache read tokens 通常是独立 token，TokKit 会按不同供应商语义分别计价。
- `Credits`：供应商 credits，和美元分开保留。
- `Records`：当前行背后的归一化记录数量。

为什么 Prompt 往往远大于 Output：

- AI 编码 agent 会反复发送仓库上下文、工具调用轨迹、文件片段和对话历史。
- Cached Prompt 仍然是 Prompt 体量，只是通常价格更低。
- Output 常常只是 patch、命令或解释，远小于生成它所需要的上下文。

## 价格与预算

查看内置价格：

```bash
tok pricing
tok pricing json
```

创建预算文件：

```bash
tok budget init
tok budget
tok budget json
```

通过 `~/.tokkit/pricing.json` 覆盖价格：

```json
{
  "GPT-5.4": {
    "input_per_million": 2.7,
    "cached_input_per_million": 0.27,
    "output_per_million": 16.0
  },
  "Claude Sonnet 4.6": {
    "input": 3.2,
    "cached_input": 0.32,
    "output": 16.0
  }
}
```

说明：

- `Est.$` 是本地估算，不是供应商账单。
- 模型价格变化后需要更新内置价格或本地覆盖文件。
- `partial` 和 `estimated` 来源可能没有足够字段用于估价。
- Warp 这类 credits 会保留在 `Credits`，不会自动换算成美元。

## Augment Capture

TokKit 可以估算历史 Augment 使用量。对于新请求，也可以安装本地 VS Code
扩展 capture hook：

```bash
tok augment status
tok augment install
tok scan augment
tok augment remove
```

安装后，新 Augment usage 会写入：

```text
~/.tokkit/augment-usage.ndjson
```

然后通过 `tok scan augment` 导入 SQLite 台账。

## Kaku 代理模式

对于可以配置 OpenAI-compatible endpoint 的工具，TokKit 可以通过本地代理
捕获精确 usage：

```bash
tokkit serve-proxy \
  --host 127.0.0.1 \
  --port 8765 \
  --upstream-base-url https://api.example.com/v1 \
  --timezone Asia/Shanghai
```

然后把客户端指向：

```toml
base_url = "http://127.0.0.1:8765"
```

## macOS 自动化

安装 LaunchAgents 后可以周期性扫描和生成日报：

```bash
./scripts/install_launchd.sh
```

卸载：

```bash
./scripts/uninstall_launchd.sh
```

## 环境变量

```bash
TOK_AUTO_SCAN_BEFORE_REPORTS=0 tok today
TOK_AUTO_SCAN_TARGET=codex tok last 7
TOK_AUTO_SCAN_TARGET=all tok month
```

`TOK_AUTO_SCAN_TARGET` 支持：

```text
all, codex, claude-code, augment, chatgpt, copilot, warp, codebuddy, cursor, trae
```

## 准确性与隐私

TokKit 面向个人本地用量台账，不替代供应商账单后台。

- 数据默认保存在本地。
- 官方导出和本地日志可能包含私有 prompt 或文件上下文。
- 分享报告前应先检查内容。
- `estimated` 更适合趋势分析，不适合对账。
- `exact` 也取决于上游日志或响应本身是否可靠。

## 进一步阅读

- [产品简介](docs/PRODUCT_BRIEF.md)
- [Positioning and roadmap](docs/POSITIONING_AND_ROADMAP.md)
- [定位与路线图（简体中文）](docs/POSITIONING_AND_ROADMAP.zh-CN.md)
- [GitHub 发布计划](docs/GITHUB_PUBLISH_PLAN.md)
