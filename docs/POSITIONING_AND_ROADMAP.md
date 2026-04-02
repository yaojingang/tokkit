# TokLedger Positioning and Roadmap

## One-line positioning

TokLedger is the local-first usage ledger for AI coding tools. It tracks
tokens, cost, models, terminals, and clients across desktop assistants, IDE
extensions, and local proxies without requiring SDK instrumentation for
log-based sources.

## Product thesis

Most LLM observability products are built for teams shipping AI applications.
TokLedger is built for individuals and small teams using many AI coding tools
on one machine. The product wins by treating local AI usage as an accounting
problem first, not an LLMOps platform problem.

## What TokLedger is

- A local SQLite ledger for AI coding tool usage
- A normalization layer across exact, partial, and estimated sources
- A terminal-first reporting workflow for daily and multi-day usage review
- A low-friction adapter layer combining log-based and proxy-based collection

## What TokLedger is not

- Not a generic cloud LLM observability platform
- Not a prompt playground or evaluation suite
- Not a hosted team dashboard that requires every app to be instrumented
- Not a vendor-billing replacement or a fake “all numbers are exact” product

## Core strengths to reinforce

### 1. Local-first by default

- Data stays on the machine unless the user explicitly exports it
- Reports, trends, and cost estimates work offline
- Privacy-sensitive workflows can keep prompt content out of the ledger while
  still storing usage metadata

### 2. Built for desktop AI tools and coding assistants

- Optimize for Codex, Kaku, Warp, Claude Code, Cursor, VS Code assistants,
  Trae, Windsurf, and similar workflows
- Make `app`, `client`, `terminal`, `workspace`, and `session` first-class
  dimensions in the data model
- Treat “AI coding daybook” as a primary user experience, not a side panel

### 3. No SDK, low-friction adoption

- Prefer log-based adapters when local usage files already exist
- Use local proxies only when exact accounting requires request/response access
- Minimize configuration and avoid forcing users to rewrite their setup

### 4. Unified accounting before everything else

- Standardize `tokens`, `cost`, `model`, `provider`, `terminal`, `client`,
  `workspace`, `session`, and `measurement_method`
- Keep `exact`, `partial`, and `estimated` explicit across the entire product
- Invest in de-duplication and attribution before adding broader platform
  features

### 5. Instant value for individual users

- `tok today` should feel useful on day one
- Auto-scan, daily report generation, shell completions, and trend charts
  should require little or no setup
- Product experience should feel closer to a developer utility than a platform

## Strategic wedge

TokLedger should compete on “local AI accounting for coding tools,” not on
“general LLMOps.” That wedge is defensible because most larger observability
products assume:

- code-level instrumentation
- app ownership
- centralized traffic
- team workflows

TokLedger instead assumes:

- many clients on one laptop
- fragmented local logs
- mixed precision sources
- terminal-native workflows

## Competitive angle

Against products like Langfuse, Phoenix, Helicone, Agenta, and OpenLIT,
TokLedger should emphasize:

- local-first storage and reporting
- support for desktop assistants and AI coding terminals
- honest mixed-precision accounting
- zero or low instrumentation adoption
- operator-grade CLI UX for individual users

## Product pillars

### Pillar A: Coverage

- Expand adapters across more AI coding clients
- Publish a support matrix with `exact`, `partial`, and `estimated` status
- Detect unsupported or partially supported tools clearly

### Pillar B: Accounting quality

- Improve model detection, source attribution, and workspace attribution
- Prevent double-counting across logs and proxies
- Maintain transparent pricing tables and override support

### Pillar C: Operator workflow

- Keep `tok` fast, readable, and habit-forming
- Make reports useful directly inside terminal and Kaku
- Add diagnostics, setup assistance, and lightweight alerts

## Near-term roadmap

### P0: Make the ledger trustworthy on day one

- `tok doctor` should explain adapter health, coverage level, last successful
  scan, and why usage is missing or partial
- `tok setup` should provide guided onboarding for common log-based adapters
  and local proxy flows, so a new user can get to a useful report quickly
- The support matrix should become a product surface, not just documentation:
  each client should clearly show `exact`, `partial`, `estimated`, or
  `untracked`, plus setup path and known limits
- Workspace and repository attribution should become first-class, so users can
  answer “which project consumed this?” without manual reconstruction
- Adapter coverage should expand in priority order around real AI coding
  workflows, especially Claude Code, Cursor, Windsurf, ChatGPT desktop, and
  major VS Code assistant paths where feasible

Success bar for P0:

- a new user can install TokLedger, connect the tools they already use, and
  trust the first report they see

### P1: Turn accounting into control

- Budgets should work across day, week, and month, and roll up by model,
  client, terminal, workspace, and machine
- Alerts should detect budget breaches, unusual spend spikes, rapid context
  growth, and weak cache efficiency before cost quietly drifts
- Attribution and de-duplication should become a dedicated accounting layer
  that reconciles overlapping logs, proxies, and client views into one
  explainable source of truth
- Cost breakdowns should stay explainable: uncached input, cached input,
  output, credits, pricing overrides, and method of measurement
- Exports and scheduled summaries should support both personal review and
  lightweight finance handoff without turning the product into a heavy
  dashboard

Success bar for P1:

- users can move from “I can see my usage” to “I can manage and reduce it”

### P2: Expand the surface carefully

- Menu bar or Raycast integration for quick status checks
- Session drill-down and replay-oriented investigation views
- Optional multi-machine sync while preserving local-first defaults
- Optional team mode only after the single-user ledger is strong

## Product guardrails

Do not dilute the wedge by prioritizing:

- prompt playgrounds
- eval frameworks
- hosted dashboards as the primary product
- broad LLM app instrumentation before coding-tool coverage is strong

Those are valid adjacent areas, but they should not lead the roadmap.

## Messaging guidance

### Good top-of-page framing

- Local-first usage ledger for AI coding tools
- Track tokens, cost, models, terminals, and clients across your AI workflow
- No SDK instrumentation required for log-based sources

### Good comparison framing

- Built for people using AI coding tools, not only teams shipping AI apps
- More honest about mixed-precision data than generic “usage dashboard”
- Better suited to local desktop workflows than cloud-first observability

## Success criteria

TokLedger is on the right path if users can:

- install it quickly
- see useful data on day one
- trust what is exact versus partial versus estimated
- understand where their AI spend and token load actually come from
- use it as a daily operational habit instead of a one-time dashboard
