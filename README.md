# yao-cli-tools

A continuously updated collection of small, practical CLI tools by Yao.

This repository is for focused utilities that solve real local workflow
problems: developer productivity, AI coding operations, local diagnostics,
terminal dashboards, and small automation helpers. Tools start small, stay
usable from the command line, and can grow into standalone packages when they
prove useful.

中文说明：这个仓库会持续更新各种实用小工具，主要面向本地命令行工作流、
AI 编码辅助、开发者诊断、效率工具和可复用自动化脚本。每个工具会尽量保持
独立、轻量、可直接运行，并在各自目录下提供安装和使用说明。

## Current Tools

### [TokKit](tools/tokkit/README.md)

TokKit is a lightweight, local-first usage ledger for AI coding tools. It
collects usage from local logs, official exports, and optional proxy/capture
paths, then turns fragmented AI coding activity into one local account of
tokens, estimated cost, models, terminals, and client coverage.

Highlights:

- Tracks Codex, Claude Code, Warp, Augment, Cursor, CodeBuddy, Trae, ChatGPT
  exports, GitHub Copilot usage metrics, and similar AI coding workflows.
- Keeps data in a local SQLite database under `~/.tokkit`.
- Separates `exact`, `partial`, and `estimated` records instead of mixing
  different accuracy levels.
- Provides terminal reports, JSON output, client coverage views, budget checks,
  pricing overrides, and interactive HTML reports.
- Includes synthetic demo assets for CLI, TUI-style, and HTML reporting examples.

Quick start:

```bash
git clone https://github.com/yaojingang/yao-cli-tools.git
cd yao-cli-tools/tools/tokkit
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
tok help
tok setup
tok today
tok html month
```

### [yao-scai-cli](tools/yao-scai-cli/README.md)

`yao-scai-cli` is an AI-native disk space scanner and advisor. It is designed
for finding large files and directories, reviewing space usage through CLI/TUI
flows, and building toward safer AI-assisted cleanup recommendations.

## Repository Direction

This repo will keep growing with small tools that are useful enough to share.
The intended pattern is:

- each tool lives under `tools/<tool-name>/`
- each tool has its own README, install instructions, and usage examples
- dependencies stay narrow and explicit
- tools should do one clear job well before growing in scope
- local-first workflows are preferred where privacy and speed matter

Planned updates may include:

- more AI coding workflow utilities
- local reporting and diagnostic helpers
- terminal-first productivity tools
- reusable scripts that graduate into packaged CLIs

## Layout

- `tools/`: individual tools and small packages
- `tools/tokkit`: AI coding usage ledger and report generator
- `tools/yao-scai-cli`: disk space scanner and advisor

## Contributing Notes

This is a personal tools repository, but the structure is intentionally simple:

- keep each tool self-contained
- document install and usage steps in that tool's README
- avoid unnecessary global dependencies
- prefer readable CLI behavior over hidden automation

## License

MIT
