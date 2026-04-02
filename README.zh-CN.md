# TokLedger

[English](README.md) | [简体中文](README.zh-CN.md)

[产品简介](docs/PRODUCT_BRIEF.md) | [Positioning & roadmap](docs/POSITIONING_AND_ROADMAP.md) | [定位与路线图（简体中文）](docs/POSITIONING_AND_ROADMAP.zh-CN.md)

TokLedger 是一个面向桌面 AI 编码工具的本地优先 Token 台账。它会扫描
Codex、Warp、Kaku、CodeBuddy 等工具在本机留下的使用日志、代理响应和
会话级聚合数据，把这些来源统一归一为 `exact`、`partial`、`estimated`
三类记录，落到同一个 SQLite 台账里，再输出按日期、终端、模型、来源、
客户端覆盖率、趋势和估算成本组织的终端报表。核心 CLI 是 `tokstat`，
更偏操作流的快捷命令是 `tok`。

![TokLedger terminal demo](docs/assets/tokledger-terminal-demo.svg)

## 为什么做 TokLedger

大多数 AI 编码工具都会把使用量分散在不同地方，而且精度、口径、单位都不一致。
TokLedger 的目标不是做一个“看起来都一样精确”的面板，而是把本地能够拿到的
数据统一到一套可解释的台账里，并明确标出每条数据到底是精确、部分可得，还是估算。

它的优势主要是：

- 本地优先，不依赖托管仪表盘
- 能精确统计的来源就精确统计，不能精确的明确标注
- 把多个工具统一进一个 SQLite 台账
- 支持按日期、终端、模型、来源、客户端做拆分
- 支持趋势图、成本估算和客户端覆盖率视图
- 适合终端和 Kaku 工作流，支持 `tok` 快捷命令

## 当前支持的数据来源

- Codex Desktop 和 Codex CLI
- Warp AI / Agent Mode
- 通过 OpenAI-compatible 本地代理接入的 Kaku Assistant
- 基于本地任务历史做估算的 CodeBuddy

所有归一化后的记录都保存在：

- `~/.tokstat/usage.sqlite`

## 精度模型

- `exact`：供应商日志或上游响应里直接暴露了明确 usage
- `partial`：能拿到总量，但拿不到按日或按方向拆分
- `estimated`：根据本地缓存文本离线重算，不是供应商账单

当前各来源的实际情况：

- Codex：可精确拿到 `input_tokens`、`output_tokens`、`cached_input_tokens`、`reasoning_tokens`
- Kaku proxy：如果上游响应带 OpenAI 风格 `usage`，就能精确统计
- Warp：本地更适合拿会话级 token 总量和 credits，历史按日拆分是 `partial`
- CodeBuddy：根据本地任务文本估算，因此是 `estimated`

## 核心特点

- 一个总账，而不是每家工具一个面板
- 对精度诚实，不把 `partial` 和 `estimated` 伪装成 `exact`
- 支持日报和多日区间报表
- 支持模型、终端、来源、客户端覆盖率分析
- 支持通过 `launchd` 自动扫描和自动日报
- 支持 `tok`、灰色提示、自动补全等终端体验增强

## 安装

```bash
cd "/path/to/tokledger"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

安装后会得到这些命令：

- `tokstat`
- `tokledger`
- `tok`

如果你之前已经做过较早版本的 editable install，再执行一次：

```bash
python3 -m pip install -e .
```

这样可以拿到新的 `tok` 入口。

## 快速开始

扫描所有支持的适配器：

```bash
tokstat scan-all --timezone Asia/Shanghai
```

或者直接用更偏操作流的快捷命令，它会在出报表前自动扫描：

```bash
tok today
tok last 7
```

查看今天：

```bash
tokstat report-daily --date today --timezone Asia/Shanghai
```

查看最近一周：

```bash
tokstat report-range --last 7 --timezone Asia/Shanghai
```

查看客户端覆盖情况：

```bash
tokstat report-clients --date today --timezone Asia/Shanghai
tokstat report-clients --last 7 --timezone Asia/Shanghai
```

## 报表视图

日报：

- totals
- by terminal
- by model
- by source
- 对可计价的 `exact` 记录给出 `Est.$`

区间报表：

- total-token 趋势图
- 按日期合并汇总
- by terminal
- by model
- by source 明细
- 对可计价的 `exact` 记录给出 `Est.$`

客户端报表：

- blended totals
- 按 measurement method 聚合
- 按日期聚合
- 客户端覆盖率视图

## Shell 工作流

常用命令：

```bash
tok help
tok pricing
tok today
tok last 7
tok clients month
tok scan warp
```

`tok` 默认会在报表命令前自动扫描，并在扫描时显示轻量级加载提示。你也可以通过环境变量调整：

```bash
TOK_AUTO_SCAN_BEFORE_REPORTS=0 tok today
TOK_AUTO_SCAN_TARGET=codex tok last 7
```

## 成本说明

- `Est.$` 是本地 API 成本估算，不是供应商最终账单
- `tok pricing` 可以查看当前 `Est.$` 使用的价格表
- 如果存在 `~/.tokstat/pricing.json`，TokLedger 会在内置价格表之上做覆盖
- `tok pricing` 会标出每一条价格来自 `built-in` 还是 `override`
- `Credits` 会继续保留给 Warp 这类直接提供 credits 的来源
- `partial` 来源如果拿不到方向拆分，`Input/Output/Cached/Reasoning` 会显示 `-`

价格覆盖文件示例：

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

## macOS 自动模式

这个项目既支持手动模式，也支持自动模式。

手动模式：

- 你自己触发扫描
- 你自己按需出报表

自动模式：

- 每小时自动扫描一次
- 每天 `00:05` 自动生成前一天的日报

安装 LaunchAgents：

```bash
./scripts/install_launchd.sh
```

生成物位置：

- 数据库：`~/.tokstat/usage.sqlite`
- 日报：`~/.tokstat/reports/YYYY-MM-DD.txt`
- 日志：`~/.tokstat/logs/*.log`

卸载后台任务：

```bash
./scripts/uninstall_launchd.sh
```

## Kaku 代理

如果你想精确统计 Kaku 的 token，需要把它接到本地 OpenAI-compatible 代理前面：

```bash
tokstat serve-proxy \
  --host 127.0.0.1 \
  --port 8765 \
  --upstream-base-url https://api.vivgrid.com/v1 \
  --timezone Asia/Shanghai
```

然后把 Kaku 指向本地代理：

```toml
base_url = "http://127.0.0.1:8765"
```

代理会转发请求，并从上游响应里记录 usage。

## 进一步阅读

- `docs/PRODUCT_BRIEF.md`
- `docs/POSITIONING_AND_ROADMAP.md`
- `docs/POSITIONING_AND_ROADMAP.zh-CN.md`
- `docs/GITHUB_PUBLISH_PLAN.md`
