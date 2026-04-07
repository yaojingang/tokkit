from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .utils import default_db_path, default_report_dir


HELP_TEXT = """tok: token usage report and scan helper

Usage:
  tok
  tok help

Reports / 报表:
  tok today                 Show today's report / 查看今天的报表
                            Includes totals + by hour/source/terminal/model tables / 包含总量以及按小时、来源、终端、模型分组的表格
  tok yesterday             Show yesterday's report / 查看昨天的报表
  tok 2026-03-31            Show a specific date / 查看指定日期的报表
  tok last 7                Show last 7 days / 查看最近 7 天报表
  tok week                  Show last 7 days / 查看最近 7 天报表
  tok month                 Show last 30 days / 查看最近 30 天报表
  tok doctor                Inspect local setup and client coverage / 检查本地配置和客户端覆盖情况
  tok setup                 Inspect or apply common setup steps / 检查或执行常见安装配置步骤
  tok budget                Show budget status for today/week/month / 查看今天、本周、本月预算状态
  tok augment status        Inspect Augment capture hook state / 检查 Augment 捕获 hook 状态
  tok augment install       Install Augment capture hook / 安装 Augment 捕获 hook
  tok augment remove        Remove Augment capture hook / 移除 Augment 捕获 hook

Client coverage / 客户端汇总:
  tok clients               Show today's client coverage report / 查看今天的客户端汇总
  tok clients today         Show today's client coverage report / 查看今天的客户端汇总
  tok clients yesterday     Show yesterday's client coverage report / 查看昨天的客户端汇总
  tok clients week          Show client coverage for last 7 days / 查看最近 7 天客户端汇总
  tok clients month         Show client coverage for last 30 days / 查看最近 30 天客户端汇总
  tok clients last 7        Show client coverage for last N days / 查看最近 N 天客户端汇总

Scans / 扫描:
  tok scan codex            Manually scan Codex now / 立即手动扫描 Codex
  tok scan claude-code      Manually scan Claude Code now / 立即手动扫描 Claude Code
  tok scan augment          Manually scan Augment capture logs now / 立即手动扫描 Augment 捕获日志
  tok scan chatgpt [path]   Scan ChatGPT export estimates now / 立即扫描 ChatGPT 导出估算数据
  tok scan codebuddy        Manually scan CodeBuddy estimates now / 立即手动扫描 CodeBuddy 估算数据
  tok scan cursor           Manually scan Cursor estimates now / 立即手动扫描 Cursor 估算数据
  tok scan trae             Manually scan Trae task history now / 立即手动扫描 Trae 任务历史
  tok scan warp             Manually scan Warp now / 立即手动扫描 Warp
  tok scan all              Manually scan Codex + Claude Code + Augment + ChatGPT export + CodeBuddy + Cursor + Trae + Warp now / 立即手动扫描 Codex、Claude Code、Augment、ChatGPT 导出、CodeBuddy、Cursor、Trae 和 Warp

JSON output / JSON 输出:
  tok json today            Show today's report as JSON / 以 JSON 输出今天的报表
  tok json yesterday        Show yesterday's report as JSON / 以 JSON 输出昨天的报表
  tok json last 7           Show last 7 days as JSON / 以 JSON 输出最近 7 天报表
  tok json month            Show last 30 days as JSON / 以 JSON 输出最近 30 天报表
  tok json clients today    Show today's client report as JSON / 以 JSON 输出今天的客户端汇总
  tok json clients last 30  Show client coverage for last N days as JSON / 以 JSON 输出最近 N 天客户端汇总

Files / 文件:
  tok files                 List generated daily report files / 列出已生成的日报文件
  tok open                  Open the report directory / 打开报表目录

Pricing / 定价:
  tok pricing               Show local pricing profiles / 查看本地价格档位
                            Marks built-in vs override / 标明 built-in 或 override 来源
  tok pricing json          Show pricing profiles as JSON / 以 JSON 输出价格档位

Budget / 预算:
  tok budget                Show current budget status / 查看当前预算状态
  tok budget json           Show budget status as JSON / 以 JSON 输出预算状态
  tok budget init           Create a starter budget file / 创建预算模板文件

Auto scan / 自动扫描:
  report commands auto-scan before rendering / 报表命令会先自动扫描再输出
  TOK_AUTO_SCAN_BEFORE_REPORTS=0               disable auto scan / 关闭自动扫描
  TOK_AUTO_SCAN_TARGET=all|codex|claude-code|augment|chatgpt|warp|codebuddy|cursor|trae  choose scan target / 指定扫描目标
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "today"

    if command in {"help", "-h", "--help"}:
        print(HELP_TEXT)
        return 0

    if command == "today":
        return _run_report(["report-daily", "--date", "today"])
    if command in {"yesterday", "y"}:
        return _run_report(["report-daily", "--date", "yesterday"])
    if command == "week":
        return _run_report(["report-range", "--last", "7"])
    if command == "month":
        return _run_report(["report-range", "--last", "30"])
    if command == "last":
        days = args[1] if len(args) > 1 else "7"
        return _run_report(["report-range", "--last", days])
    if _is_date(command):
        return _run_report(["report-daily", "--date", command])
    if command == "scan":
        return _run_scan_command(args[1:])
    if command == "clients":
        return _run_clients_command(args[1:])
    if command == "json":
        return _run_json_command(args[1:])
    if command == "pricing":
        return _run_pricing_command(args[1:])
    if command == "budget":
        return _run_budget_command(args[1:])
    if command == "doctor":
        return _run_doctor_command(args[1:])
    if command == "setup":
        return _run_setup_command(args[1:])
    if command == "augment":
        return _run_augment_command(args[1:])
    if command == "files":
        return _run_files_command()
    if command == "open":
        return subprocess.run(["open", str(_report_dir())], check=False).returncode

    print(f"tok: unknown command '{command}'", file=sys.stderr)
    print("", file=sys.stderr)
    print(HELP_TEXT, file=sys.stderr)
    return 1


def _run_scan_command(args: list[str]) -> int:
    target = args[0] if args else "codex"
    if target in {"chatgpt", "chatgpt-export"}:
        command = ["scan-chatgpt-export"]
        if len(args) > 1:
            command.extend(["--export-file", args[1]])
        return _run_tokkit(command)
    mapping = {
        "codex": ["scan-codex"],
        "claude-code": ["scan-claude-code"],
        "claude": ["scan-claude-code"],
        "augment": ["scan-augment"],
        "codebuddy": ["scan-codebuddy"],
        "cursor": ["scan-cursor"],
        "trae": ["scan-trae"],
        "warp": ["scan-warp"],
        "all": ["scan-all"],
    }
    command = mapping.get(target)
    if command is None:
        print(f"tok: unsupported scan target '{target}'", file=sys.stderr)
        return 1
    return _run_tokkit(command)


def _run_clients_command(args: list[str]) -> int:
    target = args[0] if args else "today"
    if target == "today":
        return _run_report(["report-clients", "--date", "today"])
    if target in {"yesterday", "y"}:
        return _run_report(["report-clients", "--date", "yesterday"])
    if target == "week":
        return _run_report(["report-clients", "--last", "7"])
    if target == "month":
        return _run_report(["report-clients", "--last", "30"])
    if target == "last":
        days = args[1] if len(args) > 1 else "7"
        return _run_report(["report-clients", "--last", days])
    if _is_date(target):
        return _run_report(["report-clients", "--date", target])
    print(f"tok: unsupported clients target '{target}'", file=sys.stderr)
    return 1


def _run_json_command(args: list[str]) -> int:
    target = args[0] if args else "today"
    if target == "last":
        days = args[1] if len(args) > 1 else "7"
        return _run_report(["report-range", "--last", days, "--json"])
    if target == "week":
        return _run_report(["report-range", "--last", "7", "--json"])
    if target == "month":
        return _run_report(["report-range", "--last", "30", "--json"])
    if target == "clients":
        next_target = args[1] if len(args) > 1 else "today"
        if next_target == "last":
            days = args[2] if len(args) > 2 else "7"
            return _run_report(["report-clients", "--last", days, "--json"])
        if next_target == "week":
            return _run_report(["report-clients", "--last", "7", "--json"])
        if next_target == "month":
            return _run_report(["report-clients", "--last", "30", "--json"])
        return _run_report(["report-clients", "--date", next_target, "--json"])
    return _run_report(["report-daily", "--date", target, "--json"])


def _run_files_command() -> int:
    report_dir = _report_dir()
    if not report_dir.exists():
        print(f"tok: report directory not found: {report_dir}", file=sys.stderr)
        return 1
    return subprocess.run(["ls", "-lt", str(report_dir)], check=False).returncode


def _run_pricing_command(args: list[str]) -> int:
    if args and args[0] == "json":
        return _run_tokkit(["pricing", "--json"])
    return _run_tokkit(["pricing"])


def _run_budget_command(args: list[str]) -> int:
    if args and args[0] == "init":
        command = ["budget", "init"]
        if len(args) > 1 and args[1] == "--force":
            command.append("--force")
        return _run_tokkit(command)
    if args and args[0] == "json":
        return _run_report(["budget", "--json"])
    return _run_report(["budget"])


def _run_doctor_command(args: list[str]) -> int:
    if args and args[0] == "json":
        return _run_tokkit(["doctor", "--json"])
    return _run_tokkit(["doctor"])


def _run_setup_command(args: list[str]) -> int:
    command = ["setup"]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "json":
            command.append("--json")
        elif arg in {"--json", "--install-launchd", "--enable-kaku-proxy", "--migrate-home"}:
            command.append(arg)
        elif arg == "--scan-mode":
            command.extend([arg, args[idx + 1]])
            idx += 1
        elif arg == "--kaku-upstream-base-url":
            command.extend([arg, args[idx + 1]])
            idx += 1
        else:
            command.append(arg)
        idx += 1
    return _run_tokkit(command)


def _run_augment_command(args: list[str]) -> int:
    target = args[0] if args else "status"
    if target == "status":
        return _run_tokkit(["patch-augment", "--status"])
    if target in {"install", "enable"}:
        return _run_tokkit(["patch-augment"])
    if target in {"remove", "disable"}:
        return _run_tokkit(["patch-augment", "--remove"])
    if target == "json":
        next_target = args[1] if len(args) > 1 else "status"
        if next_target == "status":
            return _run_tokkit(["patch-augment", "--status", "--json"])
        if next_target in {"install", "enable"}:
            return _run_tokkit(["patch-augment", "--json"])
        if next_target in {"remove", "disable"}:
            return _run_tokkit(["patch-augment", "--remove", "--json"])
    print(f"tok: unsupported augment target '{target}'", file=sys.stderr)
    return 1


def _run_report(args: list[str]) -> int:
    auto_scan_status = _run_auto_scan_if_needed()
    if auto_scan_status != 0:
        return auto_scan_status
    return _run_tokkit(args)


def _run_auto_scan_if_needed() -> int:
    if os.environ.get("TOK_AUTO_SCAN_BEFORE_REPORTS", "1") != "1":
        return 0

    scan_command, scan_label = _resolve_scan_target(os.environ.get("TOK_AUTO_SCAN_TARGET", "all"))
    if scan_command is None:
        print(
            f"tok: unsupported auto scan target '{os.environ.get('TOK_AUTO_SCAN_TARGET', 'all')}'",
            file=sys.stderr,
        )
        return 1

    with tempfile.NamedTemporaryFile(prefix="tok-auto-scan.", suffix=".log", delete=False) as tmp:
        temp_path = Path(tmp.name)

    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            proc = subprocess.Popen(
                _tokkit_command(scan_command),
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            status = _wait_with_spinner(proc, scan_label)
        if status != 0:
            print("tok: auto-scan failed", file=sys.stderr)
            output = temp_path.read_text(encoding="utf-8")
            if output.strip():
                print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")
        return status
    finally:
        temp_path.unlink(missing_ok=True)


def _wait_with_spinner(proc: subprocess.Popen[str], label: str) -> int:
    if not sys.stderr.isatty():
        return proc.wait()

    spinner_frames = ["|", "/", "-", "\\"]
    idx = 0
    while proc.poll() is None:
        frame = spinner_frames[idx % len(spinner_frames)]
        print(f"\rtok: scanning {label}... {frame}", end="", file=sys.stderr, flush=True)
        idx += 1
        time.sleep(0.1)
    status = proc.wait()
    print("\r\033[2K", end="", file=sys.stderr, flush=True)
    return status


def _resolve_scan_target(target: str) -> tuple[list[str] | None, str]:
    mapping = {
        "codex": (["scan-codex"], "Codex"),
        "claude-code": (["scan-claude-code"], "Claude Code"),
        "claude": (["scan-claude-code"], "Claude Code"),
        "augment": (["scan-augment"], "Augment"),
        "chatgpt": (["scan-chatgpt-export"], "ChatGPT export"),
        "chatgpt-export": (["scan-chatgpt-export"], "ChatGPT export"),
        "codebuddy": (["scan-codebuddy"], "CodeBuddy"),
        "cursor": (["scan-cursor"], "Cursor"),
        "trae": (["scan-trae"], "Trae"),
        "warp": (["scan-warp"], "Warp"),
        "all": (["scan-all"], "Codex + Claude Code + Augment + ChatGPT export + CodeBuddy + Cursor + Trae + Warp"),
    }
    return mapping.get(target, (None, ""))


def _run_tokkit(args: list[str]) -> int:
    return subprocess.run(_tokkit_command(args), check=False).returncode


def _tokkit_command(args: list[str]) -> list[str]:
    command = [sys.executable, "-m", "tokkit.cli", "--db", str(_db_path())]
    timezone = os.environ.get("TOKKIT_TIMEZONE", os.environ.get("TOKSTAT_TIMEZONE"))
    if timezone:
        command.extend(["--timezone", timezone])
    command.extend(args)
    return command


def _db_path() -> Path:
    return default_db_path()


def _report_dir() -> Path:
    return default_report_dir()


def _is_date(value: str) -> bool:
    if len(value) != 10:
        return False
    return value[4] == "-" and value[7] == "-" and value.replace("-", "").isdigit()


if __name__ == "__main__":
    raise SystemExit(main())
