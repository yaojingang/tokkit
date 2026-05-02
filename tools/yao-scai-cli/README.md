# Scai

**Scai = Scan + AI**. Scai is an AI-native TUI for scanning, understanding, and safely reclaiming disk space.

Tool folder: `tools/yao-scai-cli`  
Project: `Scai`  
Command: `scai`

Scai currently focuses on disk usage scanning. The AI layer is planned as the core differentiator: it should explain what is taking space, classify cleanup risk, and suggest safe reclaim plans instead of blindly deleting files.

## Features

- Default TUI experience for finding large files and folders.
- Plain table output for scripting and non-interactive terminals.
- Short commands for common workflows.
- Safe default exclusions for system, cache, dependency, and metadata folders.
- Legacy aliases for earlier local commands: `bf` and `scan`.
- No third-party runtime dependency; implemented with Python standard library `curses`.

## Install

From this tool directory, run:

```bash
./install.sh
```

The installer creates or updates these commands in `$HOME/bin`:

- `scai`: main command, defaults to TUI.
- `bf`: legacy alias, defaults to TUI.
- `scan`: compatibility alias, defaults to plain table output.

Make sure `$HOME/bin` is in your `PATH`.

## Quick Start

```bash
scai
scai 50
scai d
scai c
scai ~/Downloads
scai d ~/Downloads 30
scai --plain
```

- `scai`: open the TUI and scan the current user home directory.
- `scai 50`: show the top 50 records.
- `scai d`: start in folder mode.
- `scai c`: scan from `/` while still applying default safety exclusions.
- `scai ~/Downloads`: scan a specific path.
- `scai --plain`: use table output for scripts or copied reports.
- `scai all`: disable default exclusions. Use only when you really need a fuller scan.

When Scai is not running in an interactive terminal, it automatically falls back to plain output. Use `scai --tui` to force the TUI.

## TUI Keys

- `q`: quit.
- `j/k` or `up/down`: move selection.
- `PageUp/PageDown`: scroll faster.
- `r`: rescan.
- `f`: switch to file mode.
- `d`: switch to directory mode.
- `/`: enter a new scan path.
- `c`: scan from `/`.
- `h`: return to the user home directory.
- `.`: scan the current working directory.
- `+/-`: adjust the result limit.
- `a`: toggle default exclusions.
- `[` / `]`: adjust `max-depth` in directory mode.
- `?`: show or hide help.

## Plain Output

```bash
scai --plain files ~/Downloads --limit 50
scai --plain dirs
scai --plain dirs ~/Downloads
scai --plain dirs --max-depth 1
scai --plain dirs ~/Downloads --max-depth 2 --limit 30
scai --plain --computer
scai --plain --all
```

`bf` remains a legacy alias. `scan` remains a table-first compatibility entry:

```bash
bf
scan
scan dirs ~/Downloads --limit 30
scan --tui
```

## Current Behavior

### `scai` / `scai --plain` / `scai files`

- Scans the current user home directory by default.
- Skips system, cache, dependency, and metadata folders by default, such as `Library`, `.Trash`, `.git`, and `node_modules`.
- `scai c` or `--computer` scans from `/` while still applying default safety exclusions.
- Counts regular files only and does not follow symlinks.
- TUI columns: index, size, format, modified time, path.
- Plain columns: index, filename, format, size, modified time.

### `scai d` / `scai --plain dirs`

- Recursively aggregates directory size.
- Does not rank the scan root itself, otherwise it would always be first.
- Supports `--max-depth`, for example `scai dirs --max-depth 1`.
- Columns: index, folder, total size, file count, modified time.

## AI Direction

Scai should not become just another `du` replacement. The target is an AI-guided disk space advisor:

- Generate a storage diagnosis after scanning.
- Recognize caches, backups, build artifacts, downloaded leftovers, and high-risk paths.
- Group suggestions into safe to clean, needs confirmation, and do not touch.
- Integrate AI through official CLIs or local model providers.
- Never read, copy, or depend on private local login tokens directly.
