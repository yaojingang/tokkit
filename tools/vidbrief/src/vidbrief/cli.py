from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .downloader import DEFAULT_SUBTITLE_LANGS, DEFAULT_VIDEO_FORMAT, download_url
from .tui import TuiResult, run_tui
from .utils import DEFAULT_OUTPUT_DIR, is_url
from .workflow import report_from_transcript_file, run_video_report, transcribe_media_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vb",
        description="Download videos, extract transcripts, and generate AI video reports.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("help", help="Show this help message and exit.")
    subparsers.add_parser("tui", help="Open the default terminal UI.")

    info_cmd = subparsers.add_parser("info", help="Extract video metadata without downloading media.")
    info_cmd.add_argument("url")
    _add_download_auth_args(info_cmd)
    info_cmd.add_argument("--json", action="store_true", help="Print raw metadata JSON.")

    download_cmd = subparsers.add_parser("download", help="Download video media, metadata, and subtitles.")
    download_cmd.add_argument("url")
    _add_output_arg(download_cmd)
    _add_download_args(download_cmd)
    download_cmd.add_argument("--audio-only", action="store_true", help="Download and convert only audio.")
    download_cmd.add_argument("--json", action="store_true", help="Print output paths as JSON.")

    run_cmd = subparsers.add_parser("run", help="Download, transcribe, and generate a report.")
    run_cmd.add_argument("url", nargs="?")
    _add_output_arg(run_cmd)
    _add_download_args(run_cmd)
    _add_ai_args(run_cmd)
    run_cmd.add_argument("--keep-audio", action="store_true", help="Keep extracted audio files.")
    run_cmd.add_argument("--json", action="store_true", help="Print output paths as JSON.")

    transcript_cmd = subparsers.add_parser("transcript", help="Transcribe a local media file.")
    transcript_cmd.add_argument("media_file", type=Path)
    _add_output_arg(transcript_cmd)
    transcript_cmd.add_argument(
        "--provider",
        choices=["auto", "openai"],
        default="openai",
        help="Transcription provider. Currently OpenAI is used for audio transcription.",
    )
    transcript_cmd.add_argument("--model", default=None, help="Transcription model.")
    transcript_cmd.add_argument("--language", default="zh-CN", help="Output or source language hint.")
    transcript_cmd.add_argument("--keep-audio", action="store_true", help="Keep extracted audio files.")
    transcript_cmd.add_argument("--json", action="store_true", help="Print output paths as JSON.")

    report_cmd = subparsers.add_parser("report", help="Generate a report from an existing transcript file.")
    report_cmd.add_argument("transcript_file", type=Path)
    _add_output_arg(report_cmd)
    report_cmd.add_argument("--provider", choices=["auto", "openai", "codex", "none"], default="auto")
    report_cmd.add_argument("--model", default=None, help="Report model.")
    report_cmd.add_argument("--language", default="zh-CN", help="Report language.")
    report_cmd.add_argument("--json", action="store_true", help="Print output paths as JSON.")

    return parser


def _add_output_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--output",
        "--dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Defaults to {DEFAULT_OUTPUT_DIR}.",
    )


def _add_download_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        help="Pass browser cookies to yt-dlp, e.g. chrome, safari, firefox:profile.",
    )
    parser.add_argument("--cookies", type=Path, default=None, help="Netscape cookies.txt file for yt-dlp.")


def _add_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        default=DEFAULT_VIDEO_FORMAT,
        help="yt-dlp format selector. Defaults to video capped at 720p.",
    )
    parser.add_argument(
        "--sub-langs",
        default=",".join(DEFAULT_SUBTITLE_LANGS),
        help="Comma-separated exact subtitle languages passed to yt-dlp.",
    )
    parser.add_argument("--playlist", action="store_true", help="Allow playlist downloads.")
    parser.add_argument("--quiet", action="store_true", help="Reduce yt-dlp output.")
    _add_download_auth_args(parser)


def _add_ai_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--report-provider",
        choices=["auto", "openai", "codex", "none"],
        default="auto",
        help="Provider used to generate the final report.",
    )
    parser.add_argument("--report-model", default=None, help="Report model.")
    parser.add_argument(
        "--transcribe-provider",
        choices=["auto", "openai", "none"],
        default="auto",
        help="Provider used when subtitles are unavailable.",
    )
    parser.add_argument("--transcribe-model", default=None, help="Audio transcription model.")
    parser.add_argument("--language", default="zh-CN", help="Report language and transcription language hint.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(_normalize_argv(raw_argv))

    try:
        if args.command is None:
            return _cmd_tui()
        if args.command == "help":
            print(render_help())
            return 0
        if args.command == "tui":
            return _cmd_tui()
        if args.command == "info":
            return _cmd_info(args)
        if args.command == "download":
            return _cmd_download(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "transcript":
            return _cmd_transcript(args)
        if args.command == "report":
            return _cmd_report(args)
    except KeyboardInterrupt:
        print("\nvb: cancelled", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"vb: error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_interactive() -> int:
    if not sys.stdin.isatty():
        raise RuntimeError("interactive mode requires a terminal; pass a URL with: vb run <url>")

    print("Video report guided mode")
    url = _prompt_url()
    output = Path(_prompt_default("Output directory", str(DEFAULT_OUTPUT_DIR)))
    cookies_from_browser = _prompt_default("Browser cookies, optional (chrome/safari/firefox)", "")
    report_provider = _prompt_choice(
        "Report provider",
        ("auto", "openai", "codex", "none"),
        _default_interactive_provider(),
    )
    language = _prompt_default("Report language", "zh-CN")

    args = argparse.Namespace(
        url=url,
        output=output,
        format=DEFAULT_VIDEO_FORMAT,
        sub_langs=",".join(DEFAULT_SUBTITLE_LANGS),
        playlist=False,
        quiet=False,
        cookies_from_browser=cookies_from_browser or None,
        cookies=None,
        report_provider=report_provider,
        report_model=None,
        transcribe_provider="auto",
        transcribe_model=None,
        language=language,
        keep_audio=False,
        json=False,
    )
    return _cmd_run(args)


def _cmd_tui() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("TUI mode requires an interactive terminal; pass a URL with: vb run <url>")

    result = run_tui(default_output_dir=DEFAULT_OUTPUT_DIR, default_report_provider=_default_interactive_provider())
    if result is None:
        print("vb: cancelled")
        return 0

    print(f"vb: running {result.action} for {result.url}")
    return _run_tui_result(result)


def _run_tui_result(result: TuiResult) -> int:
    common = {
        "url": result.url,
        "output": result.output,
        "format": result.video_format,
        "sub_langs": ",".join(DEFAULT_SUBTITLE_LANGS),
        "playlist": False,
        "quiet": False,
        "cookies_from_browser": result.cookies_from_browser,
        "cookies": None,
        "json": False,
    }
    if result.action == "run":
        return _cmd_run(
            argparse.Namespace(
                **common,
                report_provider=result.report_provider,
                report_model=None,
                transcribe_provider="auto",
                transcribe_model=None,
                language=result.language,
                keep_audio=False,
            )
        )
    if result.action == "info":
        return _cmd_info(argparse.Namespace(url=result.url, cookies_from_browser=result.cookies_from_browser, cookies=None, json=False))
    if result.action == "download":
        return _cmd_download(argparse.Namespace(**common, audio_only=False))
    raise RuntimeError(f"unsupported TUI action: {result.action}")


def render_help() -> str:
    return f"""vb - video brief CLI / 视频下载、解析、报告工具

Usage / 用法:
  vb                              Start TUI mode / 进入终端图形界面
  vb tui                          Start TUI mode / 进入终端图形界面
  vb help                         Show this help / 显示帮助
  vb info <url>                   Show metadata only / 只查看视频信息
  vb run <url>                    Download, transcribe, report / 下载、转写、生成报告
  vb download <url>               Download video and subtitles / 只下载视频和字幕
  vb report <transcript.md>       Generate report from transcript / 从转写文件生成报告
  vb transcript <video-file>      Transcribe local media / 转写本地视频或音频

Common examples / 常用例子:
  vb
  vb tui
  vb run "https://www.youtube.com/watch?v=VIDEO_ID"
  vb info "https://www.youtube.com/watch?v=VIDEO_ID"
  vb run "视频URL" --dir "/Users/laoyao/Downloads"
  vb run "视频URL" --cookies-from-browser chrome
  vb report ./video.transcript.md --provider codex

Defaults / 默认:
  Output directory / 输出目录: {DEFAULT_OUTPUT_DIR}
  Video quality / 视频清晰度: capped at 720p by default / 默认最高 720p
  Report provider / 报告模型: auto, prefers OpenAI API then local Codex / 自动选择，优先 OpenAI API，其次本机 Codex

Useful options / 常用参数:
  --dir, -o, --output <path>       Set output directory / 指定输出目录
  --cookies-from-browser chrome    Use browser login cookies for video site / 复用浏览器登录态
  --report-provider codex          Use local Codex CLI for report / 用本机 Codex 生成报告
  --report-provider none           Skip AI report / 不调用 AI，只生成基础报告
  --format best                    Download highest available quality / 下载最高可用清晰度
  --json                           Print machine-readable output / 输出 JSON

TUI controls / TUI 按键:
  Up/Down                          Move between fields / 上下移动
  Left/Right                       Change selected option / 左右切换选项
  Type or paste                    Edit URL and output path / 输入或粘贴 URL 和目录
  Ctrl-U                           Clear current text field / 清空当前文本字段
  Enter                            Move next or Start / 下一项或执行
  Esc                              Exit TUI / 退出 TUI

Tips / 提示:
  In TUI mode, paste the URL into the URL field, choose options, then Start.
  进入 TUI 后，把视频链接粘贴到 URL 字段，选择参数，然后执行 Start。
"""


def _cmd_info(args: argparse.Namespace) -> int:
    result = download_url(
        args.url,
        DEFAULT_OUTPUT_DIR,
        cookies_from_browser=args.cookies_from_browser,
        cookie_file=args.cookies,
        write_subs=False,
        download=False,
        quiet=True,
    )
    if args.json:
        print(json.dumps(result.info, ensure_ascii=False, indent=2))
    else:
        metadata = result.metadata()
        for key, value in metadata.items():
            print(f"{key}: {value}")
    return 0


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    for command in ("info", "download", "run"):
        for scheme in ("http://", "https://"):
            prefix = f"{command}{scheme}"
            if argv[0].startswith(prefix):
                return [command, f"{scheme}{argv[0][len(prefix):]}", *argv[1:]]
    return argv


def _cmd_download(args: argparse.Namespace) -> int:
    result = download_url(
        args.url,
        args.output,
        video_format=args.format,
        audio_only=args.audio_only,
        sub_langs=_split_csv(args.sub_langs),
        cookies_from_browser=args.cookies_from_browser,
        cookie_file=args.cookies,
        playlist=args.playlist,
        quiet=args.quiet,
        download=True,
    )
    payload = _download_payload(result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_payload(payload)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.url and sys.stdin.isatty():
        args.url = _prompt_url()
    if not args.url:
        raise RuntimeError("missing video URL; pass one with: vb run <url>")
    if not is_url(args.url):
        raise RuntimeError("run expects an http(s) video URL")
    result = run_video_report(
        args.url,
        args.output,
        video_format=args.format,
        cookies_from_browser=args.cookies_from_browser,
        cookie_file=args.cookies,
        playlist=args.playlist,
        sub_langs=_split_csv(args.sub_langs),
        transcribe_provider=args.transcribe_provider,
        transcribe_model=args.transcribe_model or "gpt-4o-mini-transcribe",
        report_provider=args.report_provider,
        report_model=args.report_model,
        output_language=args.language,
        keep_audio=args.keep_audio,
        quiet=args.quiet,
    )
    payload = {
        **_download_payload(result.download),
        "transcript": str(result.transcript.transcript_path),
        "transcript_source": result.transcript.source,
        "report": str(result.report_path),
        "report_provider": result.report_provider,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_payload(payload)
    return 0


def _cmd_transcript(args: argparse.Namespace) -> int:
    if not args.media_file.exists():
        raise RuntimeError(f"media file does not exist: {args.media_file}")
    result = transcribe_media_file(
        args.media_file,
        args.output,
        provider=args.provider,
        model=args.model or "gpt-4o-mini-transcribe",
        output_language=args.language,
        keep_audio=args.keep_audio,
    )
    payload = {
        "transcript": str(result.transcript_path),
        "source": result.source,
        "audio": str(result.audio_file) if result.audio_file else None,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_payload(payload)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    if not args.transcript_file.exists():
        raise RuntimeError(f"transcript file does not exist: {args.transcript_file}")
    report_path = report_from_transcript_file(
        args.transcript_file,
        args.output,
        provider=args.provider,
        model=args.model,
        output_language=args.language,
    )
    payload = {"report": str(report_path), "provider": args.provider}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_payload(payload)
    return 0


def _download_payload(result: Any) -> dict[str, Any]:
    return {
        "title": result.title,
        "id": result.video_id,
        "media": str(result.media_file) if result.media_file else None,
        "info_json": str(result.info_json) if result.info_json else None,
        "subtitles": [str(path) for path in result.subtitle_files],
    }


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _prompt_url() -> str:
    while True:
        value = input("Paste video URL only: ").strip()
        if value in {"vb", "vb run", "vidbrief", "vidbrief run"}:
            print("You are already inside vb. Paste the http(s) video URL here.")
            continue
        if is_url(value):
            return value
        print("Please enter a valid http(s) URL.")


def _prompt_default(label: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_choice(label: str, choices: tuple[str, ...], default: str) -> str:
    choice_list = "/".join(choices)
    while True:
        value = _prompt_default(f"{label} ({choice_list})", default)
        if value in choices:
            return value
        print(f"Please choose one of: {choice_list}")


def _default_interactive_provider() -> str:
    return "codex" if shutil.which("codex") else "auto"


def _print_payload(payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if isinstance(value, list):
            print(f"{key}:")
            for item in value:
                print(f"  - {item}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
