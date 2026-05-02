# vb

`vb` is a small local CLI that wraps `yt-dlp` for video download, extracts a transcript from subtitles or audio, and generates a Markdown report with a configured AI provider.

## Install

```bash
cd "/Users/laoyao/AI Coding/yao-cli-tools/tools/vidbrief"
python3 -m pip install -e ".[openai]"
```

`ffmpeg` is required when a site has no usable subtitles and the tool must transcribe audio.

The package still installs `vidbrief` as a backward-compatible alias, but `vb` is the primary command.

## Quick Start

```bash
vb
```

`vb` opens the default TUI. The TUI lets you set:

- video URL
- action: run, info, or download
- output directory
- optional browser cookies
- report provider
- report language
- quality

You can still run it in one line:

```bash
vb run "https://www.youtube.com/watch?v=VIDEO_ID"
```

In TUI mode, paste the video URL into the URL field. Direct commands like `vb run "..."` still work.

Outputs are written to the Mac Downloads folder by default. On this machine that resolves to:

```bash
/Users/laoyao/Downloads
```

In Finder this may display as `下载`.

- downloaded media
- `.info.json` metadata from `yt-dlp`
- subtitle files when available
- `.transcript.md`
- `.report.md`

Video downloads are capped at 720p by default to keep report runs practical. Use `--format best` if you need the highest available quality.

## Commands

Show help:

```bash
vb help
```

Open the TUI explicitly:

```bash
vb tui
```

Download only:

```bash
vb download "https://example.com/video" --output ./videos
```

You can also use `--dir`:

```bash
vb run "https://example.com/video" --dir "/Users/laoyao/下载"
```

End-to-end report:

```bash
vb run "https://example.com/video" --output ./reports
```

Prompt for the URL, then run the same end-to-end flow:

```bash
vb run
```

Use browser cookies for gated video pages:

```bash
vb run "https://example.com/video" --cookies-from-browser chrome
```

Generate a report from an existing transcript:

```bash
vb report ./my-video.transcript.md --provider codex
```

Transcribe a local media file with OpenAI:

```bash
OPENAI_API_KEY=... vb transcript ./video.mp4 --provider openai
```

## Shell Hints

This machine also loads `~/.config/kaku/zsh/vb-experience.zsh` from `~/.zshrc`.

In a new zsh terminal, typing `vb ` shows gray inline suggestions for common commands, and Tab completes subcommands and common options.

## AI Providers

`vb` never reads browser cookies or private app token files for AI access. It supports regular provider entry points:

- `openai`: uses `OPENAI_API_KEY`, and honors `OPENAI_BASE_URL` for compatible gateways.
- `codex`: calls the local `codex exec` command in read-only mode, reusing the machine's existing Codex login if present.
- `none`: writes a deterministic non-AI report shell with metadata and transcript preview.
- `auto`: uses OpenAI when `OPENAI_API_KEY` is set, then Codex CLI when available, then `none`.

Useful environment variables:

```bash
export OPENAI_API_KEY=...
export VIDBRIEF_REPORT_MODEL=gpt-4.1-mini
export VIDBRIEF_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
```

## Notes

`vb` uses the `yt_dlp.YoutubeDL` Python API directly instead of parsing unstable human CLI output. This keeps metadata and file discovery more reliable.
