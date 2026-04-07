# TokKit

[English](README.md) | [简体中文](README.zh-CN.md)

[Product brief](docs/PRODUCT_BRIEF.md) | [Positioning & roadmap](docs/POSITIONING_AND_ROADMAP.md) | [定位与路线图（简体中文）](docs/POSITIONING_AND_ROADMAP.zh-CN.md)

TokKit is the lightweight, local-first usage ledger for AI coding tools.
It helps individual developers track tokens, cost, models, terminals, and
clients across Codex, Claude Code, Warp, Kaku, Cursor, CodeBuddy, Augment,
ChatGPT exports, and similar desktop workflows
without requiring SDK instrumentation for log-based sources. The core CLI is
`tokkit`, with `tok` as the operator shortcut and `tokstat` kept as a compatibility alias.

In one sentence:

- TokKit is a lightweight, local-first ledger that turns fragmented AI
  coding tool usage into one honest, terminal-first account of tokens and
  cost.

Example: `tok last 7`

![TokKit range report example](docs/assets/tokkit-range-report-example.svg)

Example: `tok help`

![TokKit help example](docs/assets/tokkit-help-example.svg)

## Why it is different

Most LLM observability products assume you own the application and can add
instrumentation. TokKit starts from a different assumption: you are using
several AI coding tools on one machine and need one trustworthy local ledger.

What TokKit emphasizes:

- Lightweight by design: one local SQLite ledger, one terminal workflow, no
  hosted dashboard requirement
- Local-first by default: data stays on your machine unless you export it
- Honest accounting: `exact`, `partial`, and `estimated` are explicit instead
  of being mixed together
- Built for AI coding tools: terminals, desktop assistants, IDE extensions,
  and local proxies
- Low-friction adoption: scan local logs where possible, proxy only where
  exact accounting needs request/response usage
- Personal operator workflow: daily reports, trends, pricing, shell
  autosuggest, and fast CLI output
- Fast local diagnostics: `tok doctor` explains setup state, coverage, and likely next steps
- Guided local onboarding: `tok setup` inspects the current machine state and can apply common setup steps

## Supported sources

- Codex Desktop and Codex CLI
- Warp AI / Agent Mode
- Kaku Assistant through an OpenAI-compatible local proxy
- ChatGPT official data export (`conversations.json` or export zip)
- Cursor from local sentry telemetry estimation
- CodeBuddy from local task-history estimation

All normalized records are stored in `~/.tokkit/usage.sqlite` by default. If an
existing `~/.tokstat` directory is present, TokKit will continue using it
unless you move to the new path.

## Accuracy model

- `exact`: vendor logs or upstream responses expose concrete usage values
- `partial`: useful totals exist, but per-day or per-direction detail is limited
- `estimated`: usage is reconstructed from local cached text, not provider usage

Current source behavior:

- Codex: exact for `input_tokens`, `output_tokens`, `cached_input_tokens`, and `reasoning_tokens`
- Claude Code: exact from local Claude session JSONL, including VS Code entrypoints when present
- Kaku proxy: exact when the upstream response includes OpenAI-style `usage`
- Warp: partial for historical day-level backfill because local data is conversation-based
- ChatGPT export: estimated from official exported conversation text, useful for longitudinal local accounting rather than billable usage
- Cursor: estimated from local sentry `ex_hs2` events, useful for directional local accounting rather than billable usage
- CodeBuddy: estimated from locally cached task text
- Augment: historical local logs still cannot backfill exact usage, but TokKit can capture exact usage from new Augment requests by patching the local VS Code extension at runtime and scanning `~/.tokkit/augment-usage.ndjson`

## Highlights

- One ledger across tools instead of separate vendor dashboards
- Lightweight local CLI instead of a hosted observability stack
- Honest reporting instead of pretending every number is equally precise
- Daily and multi-day summaries with grouped tables and trend charts
- Model, terminal, source, and client coverage breakdowns
- Local pricing overrides and estimated API cost views
- Budget tracking for today, last 7 days, and month-to-date
- Automatic scan and daily report support via `launchd`
- Fast operator UX with `tok`, inline hints, autosuggest, and completion

## Install in 3 steps

```bash
cd "/path/to/tokkit"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

That installs:

- `tokkit`
- `tok`
- `tokstat` compatibility alias

If you already had an older editable install, rerun `python3 -m pip install -e .`
to pick up the `tok` entry point.

## First-run flow

1. Verify the install and available commands:

```bash
tok help
tok setup
tok doctor
tok pricing
tok budget
tok augment status
tok scan chatgpt
tok scan chatgpt ~/Downloads/chatgpt-export.zip
```

2. See your first report:

```bash
tok today
tok last 7
```

3. If you prefer the lower-level CLI:

```bash
tokkit report-daily --date today --timezone Asia/Shanghai
tokkit report-range --last 7 --timezone Asia/Shanghai
```

4. If you use Augment in VS Code, install the local runtime capture hook once:

```bash
tok augment install
tok scan augment
```

## Optional setup paths

Use the guided setup command if you want one place to inspect or apply the common local steps:

```bash
tok setup
tok setup --install-launchd --scan-mode codex
tok setup --enable-kaku-proxy --install-launchd --kaku-upstream-base-url https://api.vivgrid.com/v1
tok budget init
tok augment install
tok scan chatgpt
```

### Manual scanning

Scan all supported adapters explicitly:

```bash
tokkit scan-all --timezone Asia/Shanghai
```

### Precision for Kaku

To capture Kaku usage precisely, run the local OpenAI-compatible proxy and
point Kaku at it:

```bash
tokkit serve-proxy \
  --host 127.0.0.1 \
  --port 8765 \
  --upstream-base-url https://api.vivgrid.com/v1 \
  --timezone Asia/Shanghai
```

Then set:

```toml
base_url = "http://127.0.0.1:8765"
```

### Automatic mode on macOS

Install the LaunchAgents if you want hourly scans and a daily report at
`00:05`:

```bash
./scripts/install_launchd.sh
```

Remove them with:

```bash
./scripts/uninstall_launchd.sh
```

## Report commands

The operator shortcut auto-scans before rendering reports:

```bash
tok today
tok last 7
```

Lower-level equivalents:

```bash
tokkit report-daily --date today --timezone Asia/Shanghai
tokkit report-range --last 7 --timezone Asia/Shanghai
tokkit report-clients --date today --timezone Asia/Shanghai
tokkit report-clients --last 7 --timezone Asia/Shanghai
```

## Report views

Daily report:

- totals
- by hour
- by terminal
- by model
- by source
- estimated API cost for priced exact records

Range report:

- total-token trend chart
- date-merged summary
- by terminal
- by model
- by source detail
- estimated API cost for priced exact records

Client report:

- blended totals
- by measurement method
- by date
- by client coverage

## Shell workflow

If you use the optional `tok` shortcut, common flows become:

```bash
tok help
tok setup
tok doctor
tok pricing
tok budget
tok augment status
tok today
tok last 7
tok clients month
tok scan warp
```

`tok` defaults to auto-scan before report commands and shows a lightweight
loading indicator while scanning. You can disable or scope that behavior with:

```bash
TOK_AUTO_SCAN_BEFORE_REPORTS=0 tok today
TOK_AUTO_SCAN_TARGET=codex tok last 7
```

Cost notes:

- `Est.$` is a local API cost estimate based on built-in model pricing profiles
- `tok pricing` shows the current built-in price table used by `Est.$`
- if `~/.tokkit/pricing.json` exists, TokKit merges it over the built-in table
- legacy `~/.tokstat/pricing.json` continues to work if you are still on the old home directory
- `tok pricing` marks every row as `built-in` or `override`
- `tok budget` compares today, last 7 days, and month-to-date spend against your local budget file
- `tok budget init` creates a starter `~/.tokkit/budget.json`
- `tok doctor` summarizes local setup, launchd automation, and client coverage in one report
- `tok setup` can apply common local steps such as home migration, Kaku proxy configuration, and launchd install
- `tok augment install` patches the local Augment VS Code extension so new requests can emit exact usage into `~/.tokkit/augment-usage.ndjson`
- `tok augment status` shows whether the Augment capture hook and capture file are in place
- `tok scan augment` ingests `~/.tokkit/augment-usage.ndjson` into the SQLite ledger
- `Credits` remains separate for sources like Warp that expose vendor credits
- partial sources may show `Input/Output/Cached/Reasoning` as `-` and `Est.$` as `-`
  when only conversation-level totals are available

Override example:

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

Generated files:

- database: `~/.tokkit/usage.sqlite`
- reports: `~/.tokkit/reports/YYYY-MM-DD.txt`
- logs: `~/.tokkit/logs/*.log`

## Recommended first release framing

TokKit should be presented as:

- a Mac-first local CLI alpha
- best for people using several AI coding tools on one machine
- strongest today on daily reporting, trend visibility, and usage honesty

## Publish notes

Repository planning and release packaging notes live in:

- `docs/PRODUCT_BRIEF.md`
- `docs/POSITIONING_AND_ROADMAP.md`
- `docs/POSITIONING_AND_ROADMAP.zh-CN.md`
- `docs/GITHUB_PUBLISH_PLAN.md`

## Further reading

- `docs/PRODUCT_BRIEF.md`
- `docs/POSITIONING_AND_ROADMAP.md`
- `docs/POSITIONING_AND_ROADMAP.zh-CN.md`
- `docs/GITHUB_PUBLISH_PLAN.md`
