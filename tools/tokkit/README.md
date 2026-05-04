# TokKit

[English](README.md) | [简体中文](README.zh-CN.md)

[Product brief](docs/PRODUCT_BRIEF.md) | [Positioning & roadmap](docs/POSITIONING_AND_ROADMAP.md) | [定位与路线图（简体中文）](docs/POSITIONING_AND_ROADMAP.zh-CN.md)

TokKit is a lightweight, local-first usage ledger for AI coding tools.

It helps developers answer a simple question that most AI coding workflows do
not answer well: **where did my tokens and AI coding spend go?** TokKit scans
local tool logs, official exports, and optional runtime capture/proxy records,
then normalizes the results into one local SQLite ledger with reports by date,
model, terminal, client, source, token direction, and estimated cost.

The main operator command is `tok`. The lower-level CLI is `tokkit`.
`tokstat` is kept as a compatibility alias.

## Demo

These examples use the same synthetic demo dataset: source report totals scaled
5x, with the Claude Code Opus 4.6 / 4.7 mix boosted.

[Open the interactive HTML demo report](docs/assets/tokkit-demo-5x-claude-opus.html)

TUI-style demo dashboard:

![TokKit TUI demo screenshot](docs/assets/tokkit-tui-demo-5x-claude-opus.svg)

CLI report:

![TokKit CLI demo screenshot](docs/assets/tokkit-cli-demo-5x-claude-opus.svg)

## Why TokKit Exists

AI coding work is increasingly split across desktop apps, terminal agents, IDE
extensions, local proxies, official exports, and vendor dashboards. A single
developer may use Codex, Claude Code, Warp, Cursor, Augment, CodeBuddy, Trae,
ChatGPT, and GitHub Copilot in the same week.

The problem is that usage data is fragmented:

- Some tools expose exact token usage in local JSONL logs.
- Some only expose conversation totals or credits.
- Some require official exports or API reports.
- Some can only be estimated from local cached text.
- Vendor dashboards rarely explain terminal/client/model usage in one place.

TokKit turns those fragments into one local ledger. It does not pretend every
number has the same precision. Each record keeps a method label:

- `exact`: upstream logs or responses include concrete token fields.
- `partial`: useful totals exist, but some dimensions are missing.
- `estimated`: TokKit reconstructs usage from local cached text or metadata.

This makes reports useful without hiding uncertainty.

## How It Works

TokKit follows a local-first pipeline:

1. **Discover sources**: find known local logs, session files, official export
   files, capture files, and optional proxy records.
2. **Scan incrementally**: first scan can inspect all configured sources; later
   scans reuse checkpoints and active-target planning so common reports stay
   fast.
3. **Normalize records**: store all usage rows in `~/.tokkit/usage.sqlite` with
   source, app, model, terminal/client hints, token fields, method, timestamp,
   and metadata.
4. **Estimate cost locally**: apply built-in pricing profiles and optional
   overrides from `~/.tokkit/pricing.json`.
5. **Render reports**: produce terminal tables, JSON, client coverage reports,
   budget views, and static interactive HTML dashboards.

Generated local files:

- SQLite ledger: `~/.tokkit/usage.sqlite`
- HTML and text reports: `~/.tokkit/reports/`
- Logs and scan state: `~/.tokkit/logs/` and related state files
- Augment runtime capture, when enabled: `~/.tokkit/augment-usage.ndjson`

TokKit also keeps compatibility with older `~/.tokstat` paths where practical.

## Highlights

- One local ledger across many AI coding tools.
- No hosted dashboard required; data stays on your machine by default.
- Exact, partial, and estimated usage are explicitly separated.
- Reports by date, source, terminal, client, model, prompt, output, cached
  prompt, reasoning tokens, unsplit totals, estimated dollars, credits, and
  records.
- Interactive HTML report with Simplified Chinese by default, English toggle,
  sticky navigation, range switching, model filters, and chart tooltips.
- Incremental scanning and active-target planning keep repeated reports fast.
- Built-in model pricing plus local override support.
- Budget checks for today, last 7 days, and month-to-date.
- `tok doctor` and `tok setup` for local diagnostics and guided onboarding.
- Optional `launchd` automation for hourly scans and daily reports on macOS.
- Augment runtime capture hook for exact usage on new requests, plus historical
  local estimates.
- JSON output for scripting and downstream analysis.

## Supported Sources

Current source behavior:

- **Codex Desktop / Codex CLI**: exact usage from local logs, including prompt,
  output, cached prompt, and reasoning tokens.
- **Claude Code**: exact usage from local Claude session JSONL, including
  detectable VS Code entrypoints.
- **Warp**: partial usage from local conversation/accounting data, including
  vendor credits where available.
- **Kaku Assistant**: exact when routed through TokKit's OpenAI-compatible local
  proxy and the upstream response includes OpenAI-style `usage`.
- **Augment**: estimated historical local usage from persisted request
  selection context and checkpoint diffs; exact usage for new requests when the
  local VS Code extension capture hook is installed.
- **ChatGPT export**: estimated usage from official exported conversation text.
- **GitHub Copilot usage metrics**: partial usage from official usage metrics
  export files or GitHub API reports; Copilot CLI token totals are supported
  when present.
- **Cursor**: estimated usage from local sentry telemetry events.
- **CodeBuddy**: estimated usage from local task-history text.
- **Trae**: exact task usage when local `ui_messages.json` files include
  `tokensIn` and `tokensOut`.

## Install and Download

TokKit currently lives inside this repository under `tools/tokkit`.

### Option 1: clone and install editable

This is the recommended development/local-operator install:

```bash
git clone https://github.com/yaojingang/yao-cli-tools.git
cd yao-cli-tools/tools/tokkit
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

### Option 2: install directly from GitHub

Use this when you want the command without keeping a working checkout:

```bash
python3 -m pip install "git+https://github.com/yaojingang/yao-cli-tools.git#subdirectory=tools/tokkit"
```

### Installed commands

- `tok`: operator shortcut for daily use
- `tokkit`: lower-level CLI
- `tokstat`: compatibility alias

Requirements:

- Python 3.10+
- macOS is the best-supported local desktop environment today
- `gh` is needed only for GitHub Copilot API-backed report scanning

## Quick Start

After installation:

```bash
tok help
tok setup
tok doctor
tok today
tok last 7
tok html month
```

Common first scans:

```bash
tok scan codex
tok scan claude-code
tok scan augment
tok scan chatgpt ~/Downloads/chatgpt-export.zip
tok scan copilot --org your-org
tok scan trae
tok scan all
```

`tok scan all` bootstraps from all known sources once. After that, TokKit
prefers recent active targets so repeated report generation is faster. Use
`--full` when you want to rebuild the scan plan:

```bash
tok scan all --full
```

## Daily Usage

Human-readable reports:

```bash
tok today
tok yesterday
tok 2026-05-03
tok week
tok month
tok last 14
```

Client coverage reports:

```bash
tok clients today
tok clients week
tok clients month
tok clients last 30
```

JSON output:

```bash
tok json today
tok json last 7
tok json clients month
```

HTML reports:

```bash
tok html
tok html week
tok html last 14
tok html month
tok html open
```

Generated HTML reports are static files under `~/.tokkit/reports/`. They can be
opened locally, shared as artifacts, or used as a starting point for demos. The
first regular report or scan command each day also writes a silent last-30-days
HTML report automatically. Run `tok html` when you want to regenerate it
manually.

Daily automatic HTML generation can be configured with environment variables:

```bash
TOK_AUTO_HTML_REPORT=0 tok today
TOK_AUTO_HTML_LAST_DAYS=7 tok today
```

- `TOK_AUTO_HTML_REPORT=0`: disable daily automatic HTML generation.
- `TOK_AUTO_HTML_LAST_DAYS=7`: use a 7-day window for the automatic report
  instead of the default 30 days.

Report directory helpers:

```bash
tok files
tok open
```

## Lower-Level CLI Commands

The `tok` shortcut wraps the lower-level `tokkit` CLI. Equivalent direct
commands include:

```bash
tokkit scan-all --timezone Asia/Shanghai
tokkit report-daily --date today --timezone Asia/Shanghai
tokkit report-range --last 7 --timezone Asia/Shanghai
tokkit report-clients --last 30 --timezone Asia/Shanghai
tokkit report-html --last 30 --open
tokkit serve-proxy --host 127.0.0.1 --port 8765 --upstream-base-url https://api.example.com/v1
```

## Reports and Fields

Core token fields:

- `Total`: total tokens reported or reconstructed for the row.
- `Prompt`: input/prompt tokens, including cached prompt tokens when upstream
  reports them that way.
- `Output`: generated output tokens.
- `Cached Prompt`: prompt tokens that were served from cache.
- `Reasoning`: reasoning tokens when the provider exposes them.
- `Unsplit`: totals that could not be safely split into prompt/output fields.
- `Est.$`: local API cost estimate calculated from model pricing, prompt,
  cached prompt, and output tokens. OpenAI cached tokens are usually included in
  input totals, while Claude/Anthropic cache-read tokens are separate billable
  tokens; TokKit prices those provider semantics differently.
- `Credits`: vendor credit units, kept separate from dollars.
- `Records`: number of normalized usage records behind the row.

Why prompt can be much larger than output:

- AI coding agents resend large repository context, tool traces, file excerpts,
  and conversation history.
- Cached prompt tokens still count as prompt volume, even when priced lower.
- Output is often a short patch, command, or explanation compared with the
  context needed to produce it.

## Pricing and Budgets

View built-in pricing:

```bash
tok pricing
tok pricing json
```

Create a budget file:

```bash
tok budget init
tok budget
tok budget json
```

Override pricing by creating `~/.tokkit/pricing.json`:

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

Notes:

- `Est.$` is a local estimate, not a vendor bill.
- Pricing profiles may lag provider pricing changes unless updated.
- Partial or estimated sources may not have enough fields for cost estimates.
- Warp-style credits remain in `Credits` and are not converted to dollars.

## Augment Capture

TokKit can estimate historical Augment usage from local workspace state. For
new requests, it can also install a local VS Code extension capture hook:

```bash
tok augment status
tok augment install
tok scan augment
tok augment remove
```

When installed, new Augment usage events are written to:

```text
~/.tokkit/augment-usage.ndjson
```

Then `tok scan augment` imports those events into the SQLite ledger.

## Kaku Proxy Mode

For tools that can point to an OpenAI-compatible endpoint, TokKit can capture
exact usage through a local proxy:

```bash
tokkit serve-proxy \
  --host 127.0.0.1 \
  --port 8765 \
  --upstream-base-url https://api.example.com/v1 \
  --timezone Asia/Shanghai
```

Then configure the client to use:

```toml
base_url = "http://127.0.0.1:8765"
```

## macOS Automation

Install LaunchAgents for recurring local scans and daily reports:

```bash
./scripts/install_launchd.sh
```

Remove them:

```bash
./scripts/uninstall_launchd.sh
```

## Environment Variables

```bash
TOK_AUTO_SCAN_BEFORE_REPORTS=0 tok today
TOK_AUTO_SCAN_TARGET=codex tok last 7
TOK_AUTO_SCAN_TARGET=all tok month
```

`TOK_AUTO_SCAN_TARGET` supports:

```text
all, codex, claude-code, augment, chatgpt, copilot, warp, codebuddy, cursor, trae
```

## Accuracy and Privacy

TokKit is designed for local personal accounting. It is not a replacement for
provider billing dashboards.

- Data stays local by default.
- Official exports and local logs may contain private prompts or file context.
- Share generated reports only after reviewing what they contain.
- Estimated sources are useful for trend tracking, not invoice reconciliation.
- Exact records are still only as reliable as the upstream log or response.

## Further Reading

- [Product brief](docs/PRODUCT_BRIEF.md)
- [Positioning and roadmap](docs/POSITIONING_AND_ROADMAP.md)
- [定位与路线图（简体中文）](docs/POSITIONING_AND_ROADMAP.zh-CN.md)
- [GitHub publish plan](docs/GITHUB_PUBLISH_PLAN.md)
