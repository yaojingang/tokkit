# Scai

**Scai = Scan + AI**. Scai is an AI-native disk space advisor: CLI for decisions, TUI for exploration.

Tool folder: `tools/yao-scai-cli`  
Project: `Scai`  
Command: `scai`

Scai is not meant to be only another `du` wrapper. The goal is to scan disk usage, classify what matters, explain cleanup risk, and generate safe reclaim plans.

## Features

- CLI-first Space Brief as the default experience.
- Dynamic scan progress in interactive terminals.
- Top 50 file details in the default brief, with `scai more` for longer lists.
- TUI browser for interactive exploration.
- Rule analysis engine for caches, build artifacts, archives, media, backups, data files, and risky system paths.
- Cleanup plan generation with no deletion side effects.
- Optional AI diagnosis through the official `codex exec` CLI when available.
- Terminal-friendly AI Markdown rendering for headings, emphasis, lists, links, and code blocks.
- Plain table output for largest files and folders.
- No third-party runtime dependency; the TUI uses Python standard library `curses`.

## Install

From this tool directory, run:

```bash
./install.sh
```

The installer creates or updates these commands in `$HOME/bin`:

- `scai`: main command.
- `bf`: legacy alias.
- `scan`: compatibility alias, defaults to table-style top files.

Make sure `$HOME/bin` is in your `PATH`.

## Core Commands

```bash
scai              # Space Brief for the current directory
scai all          # safe full-computer scan from /
scai top          # largest files
scai more         # show more largest files, default Top 100
scai more 200     # show Top 200 largest files
scai dirs         # largest folders
scai tui          # open TUI browser
scai explain PATH # explain one file or folder
scai plan 20g     # generate a reclaim plan
scai ai           # ask Codex CLI to analyze the scan summary
```

Short forms still work:

```bash
scai 50
scai d
scai all
scai more
scai ~/Downloads
scai --plain ~/Downloads 30
```

## Default Brief

`scai` scans the current directory by default and prints a high-signal CLI overview instead of opening the TUI. In an interactive terminal it shows a live scanning spinner with elapsed time before printing results. Use `scai all` for a safe full-computer scan from `/`; use `--all` only when you explicitly want to disable default exclusions.

```text
Scai Space Brief

主要占用:
  1. Downloads                                  42.1 GB
  2. Projects                                   31.4 GB

可安全关注:
  - 开发缓存/构建产物: 约 8.2 GB

需要确认:
  - 历史备份/归档: 约 12.4 GB
  - 大媒体文件: 约 21.8 GB

Top 50 文件明细:
  编号          大小  风险        分类              文件
   1      3.2 GB  需要确认      大媒体文件           videos/demo.mov
   2      1.8 GB  需要确认      压缩包/镜像          Downloads/archive.zip

显示更多:
  - scai more        显示 Top 100 文件
  - scai more 200    显示 Top 200 文件

下一步:
  - scai top          查看最大文件
  - scai dirs         查看最大文件夹
  - scai tui          进入交互浏览
  - scai plan 20g     生成释放空间方案
  - scai ai           生成 AI 诊断
```

## TUI

Use the TUI when you want to browse and compare results interactively:

```bash
scai tui
scai tui ~/Downloads
scai tui ~/Projects --mode dirs
```

TUI keys:

- `q`: quit.
- `j/k` or `up/down`: move selection.
- `PageUp/PageDown`: scroll faster.
- `r`: rescan.
- `f`: switch to file mode.
- `d`: switch to directory mode.
- `/`: enter a new scan path.
- `c`: scan from `/`.
- `h`: return to the directory where Scai started.
- `.`: scan the current working directory.
- `+/-`: adjust the result limit.
- `a`: toggle default exclusions.
- `[` / `]`: adjust `max-depth` in directory mode.
- `?`: show or hide help.

## Rule Analysis

Scai classifies scan results into risk levels:

- `safe`: likely rebuildable or low-risk, such as `node_modules`, `.next`, `dist`, `target`, and cache folders.
- `review`: needs human confirmation, such as archives, downloads, media files, backups, data files, and unknown large items.
- `risky`: system or application-managed paths that should not be removed directly.

The first version is intentionally conservative. It explains why an item was classified and what action is safer.

## Reclaim Plans

`scai plan` produces a plan only; it never deletes files:

```bash
scai plan 10g
scai plan 500m ~/Downloads
scai plan 20g all
scai plan 20g ~/Projects --all
```

Plans prefer `safe` candidates first, then `review` candidates. Future cleanup execution should default to moving items to Trash and logging every action.

## AI Diagnosis

`scai ai` summarizes local scan results and passes only that JSON summary to the official `codex exec` CLI. Scai does not read file contents, does not copy local login credentials, and does not read Codex tokens. Authentication is handled by the already-installed local Codex CLI and its existing login state.

The AI prompt contains paths, sizes, formats, rule categories, risk labels, and suggested actions. It does not include file contents. Codex runs with `--sandbox read-only`, so the AI diagnosis step is analysis-only.

AI responses are rendered for terminals: Markdown headings, bold text, lists, links, and code blocks are cleaned up so raw markers like `**text**` or `* item` do not dominate the output.

```bash
scai ai
scai ai ~/Downloads --timeout 240
```

If Codex is unavailable or times out, Scai falls back to the local rule-based Space Brief.

## Compatibility

`bf` remains a legacy alias. `scan` remains a table-first compatibility entry:

```bash
bf
scan
scan dirs ~/Downloads --limit 30
scan --tui ~/Downloads
```

`scai --plain PATH 30` maps to the old table-style top-file output.
