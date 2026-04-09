# TokKit

## Product name

- Product: `TokKit`
- CLI: `tokkit`
- Optional shell shortcut: `tok`
- Compatibility alias: `tokstat`
- Suggested GitHub repo: `yao-cli-tools`
- Tool path inside the repo: `tools/tokkit`

## One-line positioning

TokKit is a local-first token ledger for desktop AI coding tools. It turns
fragmented usage data from terminals, IDEs, and local assistants into one
consistent daily view.

## Target user

- Individual developers using multiple AI coding tools on one Mac
- Power users who switch between terminal agents and IDE assistants
- Builders who want to understand token cost, context growth, and usage habits
- People who want local reporting instead of vendor dashboards only

## Core value

Most AI tools show usage in separate places, with different definitions and
different levels of accuracy. TokKit unifies that into one local SQLite
ledger and makes the measurement method explicit.

## Product highlights

- Local-first: data stays on the machine and is stored in SQLite
- Honest accounting: separates `exact`, `partial`, and `estimated` coverage
- Cross-tool: supports Codex, Warp, Kaku proxy, and CodeBuddy estimation
- Daily workflows: reports by date, source, terminal, model, and client
- Automation-ready: hourly scans and daily reports via `launchd`
- Fast operator UX: `tok` helper, inline hints, autosuggest, and completion

## Differentiators

- Not a generic usage dashboard. It is built for AI coding workflows.
- Not vendor-specific. It combines multiple local clients into one ledger.
- Not misleading. Unknown or estimated data is labeled instead of guessed.
- Not cloud-dependent. It still works if a provider does not expose a public
  dashboard or an export API.

## Release framing

Initial release should be framed as:

- `v0.1`: single-user, Mac-first, local CLI alpha
- best for users running multiple terminal and IDE assistants
- strongest use case: daily reporting and trend visibility

## Demo flow

1. Scan local data sources with `tokkit scan-all`
2. View today with `tok today`
3. View the last week with `tok last 7`
4. View client coverage with `tok clients month`
5. Enable `launchd` for automatic scans and daily reports

## Good future extensions

- More adapters: Cursor, ChatGPT desktop, Trae, Copilot
- Cost estimation by model pricing tables
- Export to CSV, Markdown, and dashboards
- Weekly summary generation
- Team mode with multiple machines feeding one ledger
