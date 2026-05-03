from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__

BYTES_PER_KIB = 1024
BYTES_PER_MIB = 1024**2
AI_PROCESS_LIMIT = 30
AI_CLI_PRIORITY = ("codex", "claude", "gemini", "opencode")


@dataclass(frozen=True)
class MemoryCategory:
    key: str
    label: str
    bytes: int
    description: str


@dataclass(frozen=True)
class ProcessMemory:
    pid: int
    rss_bytes: int
    cpu_percent: float
    command: str
    ppid: int = 0
    vsize_bytes: int = 0
    memory_percent: float = 0.0
    state: str = ""
    software: str = ""


@dataclass(frozen=True)
class SoftwareActivity:
    name: str
    process_count: int
    active_process_count: int
    rss_bytes: int
    vsize_bytes: int
    cpu_percent: float
    top_pid: int


@dataclass(frozen=True)
class GraphicsDevice:
    name: str
    device_type: str | None
    vendor: str | None
    cores: int | None
    metal: str | None
    vram_bytes: int | None
    displays: list[str]
    utilization_percent: int | None
    renderer_utilization_percent: int | None
    tiler_utilization_percent: int | None
    allocated_system_memory_bytes: int | None
    in_use_system_memory_bytes: int | None
    in_use_driver_memory_bytes: int | None
    last_submission_pid: int | None
    last_submission_process: str | None
    notes: list[str]


@dataclass(frozen=True)
class OptimizationAction:
    title: str
    command: str
    reason: str
    risk: str


@dataclass(frozen=True)
class AiAdviceResult:
    provider: str
    command: str | None
    advice: str
    used_fallback: bool
    error: str | None = None


@dataclass(frozen=True)
class MemorySnapshot:
    platform: str
    total_bytes: int
    used_bytes: int
    available_bytes: int
    free_bytes: int
    swap_total_bytes: int | None
    swap_used_bytes: int | None
    categories: list[MemoryCategory]
    software: list[SoftwareActivity]
    processes: list[ProcessMemory]
    graphics: list[GraphicsDevice]
    details: dict[str, int | str | None]


class MemoryCollectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TuiFrame:
    lines: list[str]
    max_scroll: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mem",
        usage="mem [help|version|guide|ai|optimize|tui|completion] [top N] [watch [SECONDS]] [json] [no processes] [no guide] [ai cli PROVIDER] [ai timeout SECONDS]",
        description="查看当前电脑的内存、交换区、GPU 与软件活跃度，并给出下一步优化建议。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        epilog="""常用命令:
  mem                         显示完整内存/GPU/软件活跃度报告，并附下一步引导
  mem help                    显示所有指令与作用说明
  mem completion zsh          输出 zsh 补全脚本，支持 Tab 补全和灰色候选提示
  mem tui                     启动全屏交互式 TUI，自动刷新，可切换视图和滚动
  mem top 20                  只显示前 20 条软件和进程明细，软件统计仍基于全量进程
  mem watch 2                 每 2 秒刷新一次，用于观察优化后的变化
  mem guide                   只显示 3 个下一步引导命令
  mem ai                      复用当前 AI CLI 登录态生成诊断建议，默认优先 Codex
  mem ai cli none             不调用 AI CLI，只使用本地规则生成建议
  mem ai timeout 60           最多等待 AI CLI 60 秒
  mem optimize                生成低风险到中风险的可执行优化命令清单，不自动执行
  mem json                    输出机器可读 JSON，便于脚本或 AI 工具继续处理
  mem no processes            隐藏软件活跃度和进程明细
  mem no guide                隐藏默认报告末尾的下一步引导

动作说明:
  help                        输出这份帮助
  version                     输出版本号
  tui                         全屏交互式监控；Tab/1-4 切换视图，方向键滚动，r 刷新，q 退出
  completion zsh              输出 shell 集成脚本；source 后可补全 mem 常见指令
  guide                       输出 AI 建议、优化指令、持续观察 3 个引导命令
  ai                          读取当前快照并调用 Codex/Claude/Gemini/opencode 或本地规则给建议
  optimize                    根据当前快照生成下一步命令，例如观察、采样 GPU、退出高内存 App

输出区域:
  内存概览                    总内存、可用内存、交换区、GPU、内存压力
  诊断优先级                  按 CRIT/WARN/INFO 标出最值得先处理的问题
  内存分类                    活跃、固定、压缩、缓存/可回收、空闲等分类
  显卡/GPU                    显卡硬件、整体利用率、统一内存、最近 GPU 提交 PID
  软件活跃度                  按软件聚合 RSS、VSZ、CPU、进程数、活跃进程数
  进程明细                    按进程展示 PID、RSS、CPU、状态、软件名和命令

说明:
  macOS 普通权限通常无法直接读取进程级 GPU 占用；mem 会提示需要 sudo powermetrics 的场景。
  optimize 只打印建议命令，不会自动退出应用或执行 sudo。
  灰色候选提示需要先在 zsh 中执行 eval "$(mem completion zsh)"；如果安装了 zsh-autosuggestions，会显示 ghost text，否则按 Tab 补全。""",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["help", "version", "guide", "ai", "optimize", "tui", "completion"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "completion_shell",
        nargs="?",
        choices=["zsh"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--top", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-processes", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-guide", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--ai-cli",
        choices=["auto", "codex", "claude", "gemini", "opencode", "none"],
        default="auto",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--ai-timeout", type=float, default=180.0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--watch",
        nargs="?",
        const=2.0,
        type=float,
        default=None,
        metavar="SECONDS",
        help=argparse.SUPPRESS,
    )
    return parser


def parse_cli_args(argv: list[str] | None = None) -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = build_parser()
    raw = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(normalize_argv(raw))
    return parser, args


def normalize_argv(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    index = 0
    actions = {"help", "version", "guide", "ai", "optimize", "tui", "completion"}
    value_keywords = {"top", "watch", "cli", "timeout", "ai-cli", "ai-timeout"}
    flag_keywords = {"json"}

    while index < len(argv):
        token = argv[index]
        lowered = token.lower()

        if token in {"-h", "--help"}:
            normalized.append("help")
        elif token in {"-v", "--version"}:
            normalized.append("version")
        elif token.startswith("--"):
            normalized.append(token)
        elif lowered in actions:
            normalized.append(lowered)
        elif lowered in flag_keywords:
            normalized.append(f"--{lowered}")
        elif lowered == "no" and index + 1 < len(argv):
            next_token = argv[index + 1].lower()
            if next_token in {"process", "processes"}:
                normalized.append("--no-processes")
                index += 1
            elif next_token == "guide":
                normalized.append("--no-guide")
                index += 1
            else:
                normalized.append(token)
        elif lowered in {"no-process", "no-processes"}:
            normalized.append("--no-processes")
        elif lowered == "no-guide":
            normalized.append("--no-guide")
        elif lowered in value_keywords:
            option, consumes_value = normalize_value_option(lowered, argv, index)
            normalized.append(option)
            if consumes_value:
                normalized.append(argv[index + 1])
                index += 1
        else:
            normalized.append(token)

        index += 1

    return normalized


def normalize_value_option(token: str, argv: list[str], index: int) -> tuple[str, bool]:
    option = {
        "top": "--top",
        "watch": "--watch",
        "cli": "--ai-cli",
        "ai-cli": "--ai-cli",
        "timeout": "--ai-timeout",
        "ai-timeout": "--ai-timeout",
    }[token]

    if index + 1 >= len(argv):
        return option, False
    next_token = argv[index + 1]
    next_lowered = next_token.lower()
    reserved = {
        "help",
        "version",
        "guide",
        "ai",
        "optimize",
        "tui",
        "completion",
        "top",
        "watch",
        "json",
        "no",
        "no-process",
        "no-processes",
        "no-guide",
        "cli",
        "ai-cli",
        "timeout",
        "ai-timeout",
    }
    if next_token.startswith("-") or next_lowered in reserved:
        return option, False
    return option, True


def main(argv: list[str] | None = None) -> int:
    parser, args = parse_cli_args(argv)

    if args.completion_shell and args.action != "completion":
        parser.error("completion shell must be used with completion")
    if args.action == "tui" and args.json:
        parser.error("json cannot be combined with tui")
    if args.top is not None and args.top < 0:
        parser.error("top must be >= 0")
    if args.ai_timeout <= 0:
        parser.error("ai timeout must be > 0")
    if args.watch is not None and args.watch <= 0:
        parser.error("watch must be > 0")
    if args.json and args.watch is not None:
        parser.error("json cannot be combined with watch")

    try:
        if args.action == "help":
            print(parser.format_help())
            return 0

        if args.action == "version":
            print(f"mem {__version__}")
            return 0

        if args.action == "completion":
            print(render_completion_script(args.completion_shell or "zsh"))
            return 0

        if args.action == "tui":
            return run_tui(args)

        if args.action == "guide":
            snapshot = collect_snapshot(process_limit=0 if args.no_processes else limited_process_count(args.top, 12))
            if args.json:
                print(json.dumps({"guide": guide_commands(args.ai_cli), "actions": actions_to_dict(build_optimization_plan(snapshot))}, ensure_ascii=False, indent=2))
            else:
                print(render_guidance(snapshot, args.ai_cli))
            return 0

        if args.action == "optimize":
            snapshot = collect_snapshot(process_limit=0 if args.no_processes else args.top)
            actions = build_optimization_plan(snapshot)
            if args.json:
                print(json.dumps({"actions": actions_to_dict(actions)}, ensure_ascii=False, indent=2))
            else:
                print(render_optimization_plan(snapshot, actions))
            return 0

        if args.action == "ai":
            snapshot = collect_snapshot(process_limit=0 if args.no_processes else limited_process_count(args.top, AI_PROCESS_LIMIT))
            result = run_ai_advice(snapshot, preferred=args.ai_cli, timeout=args.ai_timeout)
            if args.json:
                print(json.dumps({"ai": asdict(result), "actions": actions_to_dict(build_optimization_plan(snapshot))}, ensure_ascii=False, indent=2))
            else:
                print(render_ai_result(snapshot, result))
            return 0

        if args.watch is None:
            snapshot = collect_snapshot(process_limit=0 if args.no_processes else args.top)
            print_output(snapshot, args)
            return 0

        while True:
            snapshot = collect_snapshot(process_limit=0 if args.no_processes else args.top)
            print("\033[2J\033[H", end="")
            print_output(snapshot, args, show_guide=False)
            sys.stdout.flush()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"mem: error: {exc}", file=sys.stderr)
        return 1


def collect_snapshot(process_limit: int | None = None) -> MemorySnapshot:
    system = platform.system()
    if process_limit == 0:
        all_processes: list[ProcessMemory] = []
    else:
        all_processes = collect_processes(limit=None)
    processes = limit_processes(all_processes, process_limit)
    software = summarize_software(all_processes, limit=process_limit)

    if system == "Darwin":
        return collect_darwin(processes, software, all_processes)
    if system == "Linux":
        return collect_linux(processes, software)
    return collect_generic(processes, software)


def collect_darwin(
    processes: list[ProcessMemory],
    software: list[SoftwareActivity],
    all_processes: list[ProcessMemory] | None = None,
) -> MemorySnapshot:
    total = int(run_command(["sysctl", "-n", "hw.memsize"]).strip())
    vm_text = run_command(["vm_stat"])
    stats, page_size = parse_vm_stat(vm_text)

    free = pages_to_bytes(stats.get("pages free", 0), page_size)
    speculative = pages_to_bytes(stats.get("pages speculative", 0), page_size)
    inactive = pages_to_bytes(stats.get("pages inactive", 0), page_size)
    active = pages_to_bytes(stats.get("pages active", 0), page_size)
    wired = pages_to_bytes(stats.get("pages wired down", 0), page_size)
    compressed = pages_to_bytes(stats.get("pages occupied by compressor", 0), page_size)
    purgeable = pages_to_bytes(stats.get("pages purgeable", 0), page_size)
    stored_compressed = pages_to_bytes(stats.get("pages stored in compressor", 0), page_size)

    reclaimable = inactive + speculative
    accounted = active + wired + compressed + reclaimable + free
    other = max(total - accounted, 0)
    available = min(total, free + reclaimable)
    used = max(total - available, 0)

    categories = [
        MemoryCategory("active", "活跃", active, "active pages"),
        MemoryCategory("wired", "固定", wired, "wired pages"),
        MemoryCategory("compressed", "压缩占用", compressed, "physical pages used by the compressor"),
        MemoryCategory("reclaimable", "缓存/可回收", reclaimable, "inactive plus speculative pages"),
        MemoryCategory("free", "空闲", free, "free pages"),
    ]
    if other >= BYTES_PER_MIB:
        categories.append(MemoryCategory("other", "其他", other, "unaccounted physical memory"))

    swap_total, swap_used = parse_darwin_swap(run_command(["sysctl", "vm.swapusage"], check=False))
    pressure_free_percent = parse_memory_pressure_free_percent(run_command(["memory_pressure"], check=False))

    details: dict[str, int | str | None] = {
        "page_size": page_size,
        "purgeable_bytes": purgeable,
        "stored_compressed_bytes": stored_compressed,
        "pressure_free_percent": pressure_free_percent,
    }
    return MemorySnapshot(
        platform="macOS",
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        free_bytes=free,
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
        categories=categories,
        software=software,
        processes=processes,
        graphics=collect_darwin_graphics(all_processes if all_processes is not None else processes),
        details=details,
    )


def collect_linux(processes: list[ProcessMemory], software: list[SoftwareActivity]) -> MemorySnapshot:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        raise MemoryCollectionError("/proc/meminfo is unavailable")
    meminfo = parse_linux_meminfo(meminfo_path.read_text(encoding="utf-8"))

    total = meminfo.get("MemTotal", 0)
    free = meminfo.get("MemFree", 0)
    available = meminfo.get("MemAvailable", free)
    buffers = meminfo.get("Buffers", 0)
    cached = meminfo.get("Cached", 0) + meminfo.get("SReclaimable", 0)
    cache_like = max(available - free, 0)
    used = max(total - available, 0)

    categories = [
        MemoryCategory("used", "已用", used, "used memory excluding generally reclaimable cache"),
        MemoryCategory("reclaimable", "缓存/可回收", cache_like, "available memory that is not currently free"),
        MemoryCategory("free", "空闲", free, "free memory"),
    ]

    return MemorySnapshot(
        platform="Linux",
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        free_bytes=free,
        swap_total_bytes=meminfo.get("SwapTotal"),
        swap_used_bytes=max(meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0), 0),
        categories=categories,
        software=software,
        processes=processes,
        graphics=collect_linux_graphics(),
        details={
            "buffers_bytes": buffers,
            "cached_bytes": cached,
            "active_bytes": meminfo.get("Active"),
            "inactive_bytes": meminfo.get("Inactive"),
        },
    )


def collect_generic(processes: list[ProcessMemory], software: list[SoftwareActivity]) -> MemorySnapshot:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        physical_pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
    except (AttributeError, OSError, ValueError) as exc:
        raise MemoryCollectionError("unsupported platform") from exc

    total = int(page_size * physical_pages)
    free = int(page_size * available_pages)
    used = max(total - free, 0)
    return MemorySnapshot(
        platform=platform.system() or "Unknown",
        total_bytes=total,
        used_bytes=used,
        available_bytes=free,
        free_bytes=free,
        swap_total_bytes=None,
        swap_used_bytes=None,
        categories=[
            MemoryCategory("used", "已用", used, "used memory"),
            MemoryCategory("free", "空闲", free, "free memory"),
        ],
        software=software,
        processes=processes,
        graphics=[],
        details={},
    )


def print_output(snapshot: MemorySnapshot, args: argparse.Namespace, show_guide: bool | None = None) -> None:
    if args.json:
        print(json.dumps(snapshot_to_dict(snapshot, include_processes=not args.no_processes), ensure_ascii=False, indent=2))
        return
    rendered = render_text(snapshot, show_processes=not args.no_processes)
    if show_guide is None:
        show_guide = not args.no_guide
    if show_guide:
        rendered += "\n\n" + render_guidance(snapshot, args.ai_cli)
    print(rendered)


def snapshot_to_dict(snapshot: MemorySnapshot, include_processes: bool = True) -> dict[str, object]:
    payload = asdict(snapshot)
    if not include_processes:
        payload["software"] = []
        payload["processes"] = []
    return payload


def limited_process_count(value: int | None, default: int) -> int | None:
    return value if value is not None else default


def render_completion_script(shell: str) -> str:
    if shell != "zsh":
        raise MemoryCollectionError(f"unsupported completion shell: {shell}")
    return ZSH_COMPLETION_SCRIPT.strip()


ZSH_COMPLETION_SCRIPT = r'''
#compdef mem
# Generated by `mem completion zsh`.

_mem() {
  local state
  typeset -A opt_args
  local -a commands ai_args no_args completion_shells

  commands=(
    'help:显示所有指令与作用说明'
    'version:输出版本号'
    'tui:启动全屏交互式监控'
    'top:限制展示行数，例如 mem top 20'
    'watch:持续刷新，例如 mem watch 2'
    'guide:显示下一步引导命令'
    'ai:复用 AI CLI 登录态生成建议'
    'optimize:生成下一步优化命令清单'
    'json:输出机器可读 JSON'
    'no:隐藏某些输出区域，例如 mem no guide'
    'completion:输出 shell 补全脚本'
  )

  ai_args=(
    'cli:选择 AI CLI，例如 mem ai cli codex'
    'timeout:设置 AI 等待秒数，例如 mem ai timeout 60'
    'top:限制 AI 读取的进程行数，例如 mem ai top 30'
  )

  no_args=(
    'processes:隐藏软件活跃度和进程明细'
    'guide:隐藏默认报告末尾的下一步引导'
  )

  completion_shells=('zsh:输出 zsh 补全脚本')

  _arguments -C \
    '1:command:->command' \
    '*::argument:->argument'

  case "$state" in
    command)
      _describe -t commands 'mem commands' commands
      ;;
    argument)
      case "${words[2]}" in
        ai)
          case "${words[CURRENT-1]}" in
            cli)
              _values 'AI CLI' auto codex claude gemini opencode none
              ;;
            timeout)
              _message '输入秒数，例如 60'
              ;;
            top)
              _message '输入行数，例如 30'
              ;;
            *)
              _describe -t ai-args 'mem ai args' ai_args
              ;;
          esac
          ;;
        completion)
          _describe -t shells 'shells' completion_shells
          ;;
        no)
          _describe -t no-args 'mem no args' no_args
          ;;
        top)
          _message '输入行数，例如 20'
          ;;
        watch)
          _message '输入刷新秒数，例如 2'
          ;;
      esac
      ;;
  esac
}

if ! whence compdef >/dev/null 2>&1; then
  autoload -Uz compinit
  compinit -i
fi

if whence compdef >/dev/null 2>&1; then
  compdef _mem mem
fi

typeset -ga _mem_autosuggest_candidates
_mem_autosuggest_candidates=(
  'mem top 20'
  'mem watch 2'
  'mem tui'
  'mem ai'
  'mem ai cli none'
  'mem ai cli codex'
  'mem ai timeout 60'
  'mem optimize'
  'mem guide'
  'mem json'
  'mem no guide'
  'mem no processes'
  'mem help'
)

_zsh_autosuggest_strategy_mem() {
  local prefix="$1"
  local candidate
  suggestion=""

  [[ "$prefix" == mem* ]] || return
  for candidate in "${_mem_autosuggest_candidates[@]}"; do
    if [[ "$candidate" == "$prefix"* && "$candidate" != "$prefix" ]]; then
      suggestion="$candidate"
      return
    fi
  done
}

if (( ${+ZSH_AUTOSUGGEST_STRATEGY} )); then
  if [[ -z "${ZSH_AUTOSUGGEST_STRATEGY[(r)mem]}" ]]; then
    ZSH_AUTOSUGGEST_STRATEGY=(mem "${ZSH_AUTOSUGGEST_STRATEGY[@]}")
  fi
else
  ZSH_AUTOSUGGEST_STRATEGY=(mem history)
fi

: ${ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE:='fg=8'}
'''


def guide_commands(preferred_ai: str = "auto") -> list[dict[str, str]]:
    ai_label = ai_cli_label(preferred_ai) or "本地规则"
    return [
        {
            "command": "mem ai",
            "title": "AI 建议",
            "description": f"复用当前 AI CLI 登录态生成优化建议，当前会优先使用 {ai_label}。",
        },
        {
            "command": "mem optimize",
            "title": "优化指令",
            "description": "基于当前内存/GPU/软件活跃度生成下一步可执行命令清单，不自动执行。",
        },
        {
            "command": "mem watch 2",
            "title": "持续观察",
            "description": "每 2 秒刷新一次，执行优化动作后观察内存、交换区和 GPU 变化。",
        },
    ]


def render_guidance(snapshot: MemorySnapshot, preferred_ai: str = "auto") -> str:
    lines = [section_title("下一步引导", width=shutil.get_terminal_size((100, 24)).columns)]
    for index, item in enumerate(guide_commands(preferred_ai), start=1):
        lines.append(f"  {index}. {pad(item['command'], 18)} {pad(item['title'], 8)} {item['description']}")
    hot = snapshot.software[0] if snapshot.software else None
    if hot:
        lines.append(f"  当前热点: {hot.name} | RSS {format_bytes(hot.rss_bytes)} | CPU {hot.cpu_percent:.1f}%")
    return "\n".join(lines)


def build_optimization_plan(snapshot: MemorySnapshot) -> list[OptimizationAction]:
    actions = [
        OptimizationAction(
            title="让 AI 读取当前快照并给出排序建议",
            command="mem ai top 30",
            reason="先用 AI CLI 复用本机登录态分析内存、交换区、GPU 和软件活跃度，避免只凭单个进程判断。",
            risk="低",
        ),
        OptimizationAction(
            title="持续观察优化效果",
            command="mem watch 2",
            reason="执行任何退出应用、关闭标签页或停止容器动作后，用连续刷新确认 RSS、swap 和 GPU 是否下降。",
            risk="低",
        ),
    ]

    if snapshot.graphics and any(device.utilization_percent and device.utilization_percent >= 35 for device in snapshot.graphics):
        actions.append(
            OptimizationAction(
                title="采样进程级 GPU 活跃度",
                command="sudo powermetrics --show-process-gpu -n 1 -i 1000",
                reason="macOS 普通权限只能看到整体 GPU 统计；这个命令可进一步定位具体 GPU 活跃进程。",
                risk="中，需要 sudo，只读取采样数据",
            )
        )

    if snapshot.swap_total_bytes and snapshot.swap_used_bytes and snapshot.swap_used_bytes / snapshot.swap_total_bytes >= 0.7:
        actions.append(
            OptimizationAction(
                title="优先处理交换区压力",
                command="mem top 20",
                reason="当前交换区占用较高，先定位 RSS 最大的软件，再决定退出、重启或减少任务。",
                risk="低",
            )
        )

    for item in snapshot.software[:5]:
        if item.rss_bytes < 256 * BYTES_PER_MIB:
            continue
        app_name = app_bundle_name_for_software(snapshot.processes, item.name)
        quit_command = quit_command_for_software(app_name) if app_name else None
        if quit_command:
            actions.append(
                OptimizationAction(
                    title=f"退出高内存软件: {app_name}",
                    command=quit_command,
                    reason=f"{item.name} 当前占用 {format_bytes(item.rss_bytes)} RSS，包含 {item.process_count} 个进程。",
                    risk="中，执行前确认未保存内容",
                )
            )

    return dedupe_actions(actions)


def render_optimization_plan(snapshot: MemorySnapshot, actions: list[OptimizationAction]) -> str:
    width = shutil.get_terminal_size((100, 24)).columns
    lines = [section_title("优化指令清单", width=width)]
    lines.extend(render_health_panel(snapshot, width=width, include_header=False))
    if snapshot.swap_total_bytes and snapshot.swap_used_bytes:
        lines.append(f"  交换区: {format_bytes(snapshot.swap_used_bytes)} / {format_bytes(snapshot.swap_total_bytes)}")
    lines.append("")
    for index, action in enumerate(actions, start=1):
        lines.append(f"{index}. [{action.risk}] {action.title}")
        lines.append(f"   $ {action.command}")
        lines.append(f"   {action.reason}")
        if index != len(actions):
            lines.append("")
    return "\n".join(lines)


def actions_to_dict(actions: list[OptimizationAction]) -> list[dict[str, str]]:
    return [asdict(action) for action in actions]


def dedupe_actions(actions: list[OptimizationAction]) -> list[OptimizationAction]:
    seen: set[str] = set()
    deduped: list[OptimizationAction] = []
    for action in actions:
        if action.command in seen:
            continue
        seen.add(action.command)
        deduped.append(action)
    return deduped


def quit_command_for_software(name: str) -> str | None:
    blocked = {"kernel_task", "launchd", "WindowServer", "SkyLight", "CoreServices", "Dock", "Finder"}
    if name in blocked or name.startswith("com.apple."):
        return None
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "{escaped}" to quit'
    return f"osascript -e {shlex.quote(script)}"


def app_bundle_name_for_software(processes: list[ProcessMemory], software: str) -> str | None:
    for process in processes:
        if process.software != software:
            continue
        match = re.search(r"/([^/]+)\.app(?:/|$)", process.command)
        if match:
            return match.group(1)
    return None


def detect_ai_cli(preferred: str = "auto") -> str | None:
    if preferred == "none":
        return None
    if preferred != "auto":
        return preferred if shutil.which(preferred) else None
    for name in AI_CLI_PRIORITY:
        if shutil.which(name):
            return name
    return None


def ai_cli_label(preferred: str = "auto") -> str | None:
    provider = detect_ai_cli(preferred)
    if provider is None:
        return None
    if provider == "codex":
        executable = shutil.which("codex")
        if executable:
            status = run_command_combined([executable, "login", "status"], timeout=3).strip()
            if status:
                return f"codex ({status})"
    return provider


def run_ai_advice(snapshot: MemorySnapshot, preferred: str = "auto", timeout: float = 180.0) -> AiAdviceResult:
    provider = detect_ai_cli(preferred)
    if provider is None:
        return AiAdviceResult(
            provider="local",
            command=None,
            advice=local_advice(snapshot),
            used_fallback=True,
            error="未检测到可用 AI CLI，或通过 ai cli none 指定了本地规则。",
        )

    prompt = build_ai_prompt(snapshot)
    command = ai_command(provider)
    if command is None:
        return AiAdviceResult(
            provider="local",
            command=None,
            advice=local_advice(snapshot),
            used_fallback=True,
            error=f"暂不支持 AI CLI: {provider}",
        )

    output_path: Path | None = None
    try:
        if provider == "codex":
            with tempfile.NamedTemporaryFile(prefix="mem-ai-", suffix=".txt", delete=False) as output_file:
                output_path = Path(output_file.name)
            command = ai_command(provider, output_path=output_path)
            if command is None:
                raise RuntimeError("cannot build codex command")
            completed = subprocess.run(command, input=prompt, check=False, capture_output=True, text=True, timeout=timeout)
            output = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else completed.stdout.strip()
            output_path.unlink(missing_ok=True)
        else:
            completed = subprocess.run(command + [prompt], check=False, capture_output=True, text=True, timeout=timeout)
            output = completed.stdout.strip()
    except subprocess.TimeoutExpired:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        return AiAdviceResult(
            provider=provider,
            command=display_ai_command(command),
            advice=local_advice(snapshot),
            used_fallback=True,
            error=f"{provider} 超时，已退回本地规则建议。",
        )
    except Exception as exc:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        return AiAdviceResult(
            provider=provider,
            command=display_ai_command(command or []),
            advice=local_advice(snapshot),
            used_fallback=True,
            error=str(exc),
        )

    error = completed.stderr.strip()
    if completed.returncode != 0 or not output:
        message = error or output or f"{provider} 没有返回建议"
        return AiAdviceResult(
            provider=provider,
            command=display_ai_command(command),
            advice=local_advice(snapshot),
            used_fallback=True,
            error=message,
        )

    return AiAdviceResult(
        provider=provider,
        command=display_ai_command(command),
        advice=terminalize_advice_text(strip_ansi(output)),
        used_fallback=False,
        error=None,
    )


def ai_command(provider: str, output_path: Path | None = None) -> list[str] | None:
    executable = shutil.which(provider)
    if executable is None:
        return None
    if provider == "codex":
        command = [executable, "exec", "--skip-git-repo-check", "--ephemeral", "--color", "never", "--sandbox", "read-only"]
        if output_path is not None:
            command.extend(["--output-last-message", str(output_path)])
        command.append("-")
        return command
    if provider == "claude":
        return [executable, "-p", "--permission-mode", "plan", "--output-format", "text", "--no-session-persistence"]
    if provider == "gemini":
        return [executable, "--approval-mode", "plan", "--output-format", "text", "-p"]
    if provider == "opencode":
        return [executable, "run", "--prompt"]
    return None


def display_ai_command(command: list[str]) -> str:
    provider = os.path.basename(command[0]) if command else ""
    if provider == "codex" and "exec" in command:
        return "codex exec (read-only, ephemeral)"
    if provider == "claude":
        return "claude prompt"
    if provider == "gemini":
        return "gemini prompt"
    if provider == "opencode":
        return "opencode run"

    visible = list(command)
    if "--output-last-message" in visible:
        index = visible.index("--output-last-message")
        if index + 1 < len(visible):
            visible[index + 1] = "<tmp>"
    return " ".join(visible)


def build_ai_prompt(snapshot: MemorySnapshot) -> str:
    payload = {
        "summary": {
            "platform": snapshot.platform,
            "total": format_bytes(snapshot.total_bytes),
            "used": format_bytes(snapshot.used_bytes),
            "used_percent": format_percent(snapshot.used_bytes, snapshot.total_bytes),
            "available": format_bytes(snapshot.available_bytes),
            "swap_used": format_bytes(snapshot.swap_used_bytes),
            "swap_total": format_bytes(snapshot.swap_total_bytes),
        },
        "categories": [
            {"label": item.label, "bytes": item.bytes, "human": format_bytes(item.bytes)}
            for item in snapshot.categories
        ],
        "graphics": [
            {
                "name": item.name,
                "utilization_percent": item.utilization_percent,
                "renderer_utilization_percent": item.renderer_utilization_percent,
                "tiler_utilization_percent": item.tiler_utilization_percent,
                "allocated_system_memory": format_bytes(item.allocated_system_memory_bytes),
                "in_use_system_memory": format_bytes(item.in_use_system_memory_bytes),
                "last_submission_pid": item.last_submission_pid,
                "last_submission_process": item.last_submission_process,
                "notes": item.notes,
            }
            for item in snapshot.graphics
        ],
        "software": [
            {
                "name": item.name,
                "rss": format_bytes(item.rss_bytes),
                "vsize": format_bytes(item.vsize_bytes),
                "cpu_percent": round(item.cpu_percent, 1),
                "process_count": item.process_count,
                "active_process_count": item.active_process_count,
                "top_pid": item.top_pid,
            }
            for item in snapshot.software[:AI_PROCESS_LIMIT]
        ],
        "processes": [
            {
                "pid": item.pid,
                "ppid": item.ppid,
                "software": item.software,
                "rss": format_bytes(item.rss_bytes),
                "vsize": format_bytes(item.vsize_bytes),
                "cpu_percent": round(item.cpu_percent, 1),
                "memory_percent": item.memory_percent,
                "state": item.state,
                "command": display_command(item.command),
            }
            for item in snapshot.processes[:AI_PROCESS_LIMIT]
        ],
        "candidate_commands": actions_to_dict(build_optimization_plan(snapshot)),
    }
    return (
        "你是本机性能优化顾问。请基于下面 mem CLI 采集到的数据，用中文给出简洁、可执行的建议。\n"
        "要求：\n"
        "1. 不要编造输入里没有的进程级 GPU/显存数据；macOS 普通权限限制要明确说明。\n"
        "2. 先判断内存、交换区、GPU 是否紧张，再指出最优先处理的软件。\n"
        "3. 给出 3 条下一步命令，优先选择低风险命令；退出应用类命令必须提醒先保存工作。\n"
        "4. 不要自动要求删除文件、清空数据库、强制结束未知进程。\n"
        "5. 输出面向终端阅读，不要使用 Markdown 代码围栏；命令单独成行并以 `$ ` 开头，优先原样使用 candidate_commands 中的命令。\n"
        "6. mem 自身命令使用空格组合，例如 `mem top 20`。\n\n"
        "数据 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def local_advice(snapshot: MemorySnapshot) -> str:
    lines = ["本地规则建议"]
    used_ratio = snapshot.used_bytes / snapshot.total_bytes if snapshot.total_bytes else 0
    if used_ratio >= 0.85:
        lines.append(f"- 内存偏紧：已用 {format_percent(snapshot.used_bytes, snapshot.total_bytes)}，优先处理 RSS 最大的软件。")
    else:
        lines.append(f"- 内存可用：已用 {format_percent(snapshot.used_bytes, snapshot.total_bytes)}，当前重点看交换区和后台常驻软件。")

    if snapshot.swap_total_bytes and snapshot.swap_used_bytes:
        swap_ratio = snapshot.swap_used_bytes / snapshot.swap_total_bytes
        if swap_ratio >= 0.7:
            lines.append(f"- 交换区压力高：{format_bytes(snapshot.swap_used_bytes)} / {format_bytes(snapshot.swap_total_bytes)}，重启高内存应用通常比清缓存更有效。")

    if snapshot.graphics:
        gpu = snapshot.graphics[0]
        if gpu.utilization_percent is not None:
            lines.append(f"- GPU 当前整体利用率约 {gpu.utilization_percent}%，进程级 GPU 归因需要 `sudo powermetrics --show-process-gpu -n 1 -i 1000`。")

    for index, item in enumerate(snapshot.software[:3], start=1):
        lines.append(
            f"- Top {index}: {item.name} 占用 {format_bytes(item.rss_bytes)} RSS，CPU {item.cpu_percent:.1f}%，进程 {item.process_count} 个。"
        )

    lines.append("")
    lines.append("建议下一步命令:")
    for action in build_optimization_plan(snapshot)[:3]:
        lines.append(f"  $ {action.command}")
        lines.append(f"    {action.title}")
    return "\n".join(lines)


def render_ai_result(snapshot: MemorySnapshot, result: AiAdviceResult) -> str:
    lines = ["AI 建议"]
    if result.used_fallback:
        lines.append(f"  来源: {result.provider} fallback")
    else:
        lines.append(f"  来源: {result.provider}")
    if result.command:
        lines.append(f"  调用: {result.command}")
    if result.error:
        lines.append(f"  备注: {result.error}")
    lines.append("")
    lines.append(terminalize_advice_text(result.advice))
    lines.append("")
    lines.append(render_guidance(snapshot))
    return "\n".join(lines)


def run_tui(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise MemoryCollectionError("tui requires an interactive terminal")

    try:
        import curses
    except ImportError as exc:
        raise MemoryCollectionError("curses is unavailable on this Python runtime") from exc

    process_limit = 0 if args.no_processes else args.top
    refresh_seconds = args.watch if args.watch is not None else 2.0

    def wrapped(stdscr: object) -> None:
        tui_loop(stdscr, curses, process_limit=process_limit, refresh_seconds=refresh_seconds)

    curses.wrapper(wrapped)
    return 0


def tui_loop(stdscr: object, curses_module: object, process_limit: int | None, refresh_seconds: float) -> None:
    stdscr.nodelay(True)
    stdscr.keypad(True)
    init_tui_colors(curses_module)
    try:
        curses_module.curs_set(0)
    except Exception:
        pass

    view_index = 0
    scroll = 0
    snapshot: MemorySnapshot | None = None
    message = "正在采集..."
    next_refresh = 0.0
    views = list(TUI_VIEWS)

    while True:
        now = time.monotonic()
        if snapshot is None or now >= next_refresh:
            try:
                snapshot = collect_snapshot(process_limit=process_limit)
                message = f"已刷新 {time.strftime('%H:%M:%S')}"
            except Exception as exc:
                message = f"采集失败: {exc}"
            next_refresh = now + refresh_seconds

        height, width = stdscr.getmaxyx()
        if snapshot is not None:
            frame = render_tui_frame(
                snapshot,
                view=views[view_index],
                scroll=scroll,
                width=width,
                height=height,
                top=process_limit,
                refresh_seconds=refresh_seconds,
                message=message,
            )
            scroll = min(scroll, frame.max_scroll)
            draw_tui_frame(stdscr, curses_module, frame)
        else:
            stdscr.erase()
            safe_addstr(stdscr, 0, 0, fit_line(message, width), 0)
            stdscr.refresh()

        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("r"), ord("R")):
            next_refresh = 0.0
            continue
        if key in (9,):
            view_index = (view_index + 1) % len(views)
            scroll = 0
            continue
        if key in (ord("1"), ord("2"), ord("3"), ord("4")):
            view_index = min(key - ord("1"), len(views) - 1)
            scroll = 0
            continue
        if key in (curses_module.KEY_DOWN, ord("j")):
            scroll += 1
        elif key in (curses_module.KEY_UP, ord("k")):
            scroll = max(0, scroll - 1)
        elif key in (curses_module.KEY_NPAGE, ord(" ")):
            scroll += max(1, height - 8)
        elif key in (curses_module.KEY_PPAGE, ord("b")):
            scroll = max(0, scroll - max(1, height - 8))
        elif key in (curses_module.KEY_HOME, ord("g")):
            scroll = 0
        elif key in (curses_module.KEY_END, ord("G")) and snapshot is not None:
            scroll = render_tui_frame(
                snapshot,
                view=views[view_index],
                scroll=scroll,
                width=width,
                height=height,
                top=process_limit,
                refresh_seconds=refresh_seconds,
                message=message,
            ).max_scroll

        if snapshot is not None:
            frame = render_tui_frame(
                snapshot,
                view=views[view_index],
                scroll=scroll,
                width=width,
                height=height,
                top=process_limit,
                refresh_seconds=refresh_seconds,
                message=message,
            )
            scroll = min(scroll, frame.max_scroll)

        time.sleep(0.08)


TUI_VIEWS = ("software", "processes", "gpu", "actions")
TUI_VIEW_LABELS = {
    "software": "软件",
    "processes": "进程",
    "gpu": "GPU",
    "actions": "优化",
}


def render_tui_frame(
    snapshot: MemorySnapshot,
    view: str,
    scroll: int,
    width: int,
    height: int,
    top: int | None,
    refresh_seconds: float = 2.0,
    message: str = "",
) -> TuiFrame:
    width = max(width, 20)
    height = max(height, 8)
    view = view if view in TUI_VIEWS else TUI_VIEWS[0]
    scroll = max(scroll, 0)

    header = render_tui_header(snapshot, view, width, refresh_seconds, message)
    body = render_tui_body(snapshot, view, width, top)
    footer = fit_line("Tab/1-4 切换视图  ↑↓/j/k 滚动  r 刷新  q 退出", width)

    available = max(height - len(header) - 1, 1)
    max_scroll = max(len(body) - available, 0)
    visible_body = body[min(scroll, max_scroll): min(scroll, max_scroll) + available]
    lines = header + visible_body + [footer]
    return TuiFrame(lines=[fit_line(line, width) for line in lines[:height]], max_scroll=max_scroll)


def render_tui_header(
    snapshot: MemorySnapshot,
    view: str,
    width: int,
    refresh_seconds: float,
    message: str,
) -> list[str]:
    title = f"mem TUI {__version__} | {snapshot.platform} | 健康: {overall_status(snapshot)}"
    used = f"内存 {format_bytes(snapshot.used_bytes)}/{format_bytes(snapshot.total_bytes)} {format_percent(snapshot.used_bytes, snapshot.total_bytes)}"
    swap = "交换区 -"
    if snapshot.swap_total_bytes is not None and snapshot.swap_used_bytes is not None:
        swap = f"交换区 {format_bytes(snapshot.swap_used_bytes)}/{format_bytes(snapshot.swap_total_bytes)} {format_percent(snapshot.swap_used_bytes, snapshot.swap_total_bytes)}"
    gpu = primary_gpu(snapshot)
    gpu_text = f"GPU {gpu.utilization_percent}%" if gpu and gpu.utilization_percent is not None else "GPU -"
    pressure = snapshot.details.get("pressure_free_percent")
    pressure_text = f"内存压力 {100 - pressure}%" if isinstance(pressure, int) else "内存压力 -"

    tabs = []
    for index, item in enumerate(TUI_VIEWS, start=1):
        label = TUI_VIEW_LABELS[item]
        tabs.append(f"[{index} {label}]" if item == view else f" {index} {label} ")

    return [
        fit_line(title, width),
        fit_line(f"{used} | {swap} | {gpu_text} | {pressure_text}", width),
        fit_line(" ".join(tabs), width),
        fit_line(f"刷新间隔 {refresh_seconds:g}s | {message}", width),
        "",
    ]


def render_tui_body(snapshot: MemorySnapshot, view: str, width: int, top: int | None) -> list[str]:
    if view == "processes":
        return render_tui_processes(snapshot, width, top)
    if view == "gpu":
        return render_tui_gpu(snapshot, width)
    if view == "actions":
        return render_tui_actions(snapshot, width)
    return render_tui_software(snapshot, width, top)


def render_tui_software(snapshot: MemorySnapshot, width: int, top: int | None) -> list[str]:
    lines = ["软件活跃度", f"  {pad('风险', 5)} {pad('RSS', 10, align='right')} {pad('CPU', 7, align='right')} {pad('进程', 5, align='right')}  软件"]
    rows = snapshot.software if top is None else snapshot.software[:top]
    if not rows:
        return lines + ["  没有可显示的软件数据。"]
    for item in rows:
        name_width = max(18, width - 35)
        lines.append(
            f"  {pad(software_risk(item, snapshot.total_bytes), 5)} "
            f"{pad(format_bytes(item.rss_bytes), 10, align='right')} "
            f"{pad(f'{item.cpu_percent:.1f}%', 7, align='right')} "
            f"{pad(str(item.process_count), 5, align='right')}  "
            f"{truncate(item.name, name_width)}"
        )
    return lines


def render_tui_processes(snapshot: MemorySnapshot, width: int, top: int | None) -> list[str]:
    lines = [
        "进程明细",
        f"  {pad('PID', 7, align='right')} {pad('RSS', 10, align='right')} {pad('CPU', 7, align='right')} {pad('软件', 18)}  进程",
    ]
    rows = snapshot.processes if top is None else snapshot.processes[:top]
    if not rows:
        return lines + ["  没有可显示的进程数据。"]
    for process in rows:
        name_width = max(18, width - 51)
        lines.append(
            f"  {pad(str(process.pid), 7, align='right')} "
            f"{pad(format_bytes(process.rss_bytes), 10, align='right')} "
            f"{pad(f'{process.cpu_percent:.1f}%', 7, align='right')} "
            f"{pad(process.software or software_name(process.command), 18)}  "
            f"{truncate(display_command(process.command), name_width)}"
        )
    return lines


def render_tui_gpu(snapshot: MemorySnapshot, width: int) -> list[str]:
    if not snapshot.graphics:
        return ["显卡/GPU", "  没有读取到 GPU 记录。"]

    lines = ["显卡/GPU"]
    for device in snapshot.graphics:
        lines.append(f"  {device.name}")
        facts = []
        if device.device_type:
            facts.append(device.device_type)
        if device.vendor:
            facts.append(device.vendor)
        if device.cores is not None:
            facts.append(f"{device.cores} cores")
        if device.metal:
            facts.append(device.metal)
        if facts:
            lines.append("    " + " | ".join(facts))
        stats = []
        if device.utilization_percent is not None:
            stats.append(f"设备 {device.utilization_percent}%")
        if device.renderer_utilization_percent is not None:
            stats.append(f"Renderer {device.renderer_utilization_percent}%")
        if device.tiler_utilization_percent is not None:
            stats.append(f"Tiler {device.tiler_utilization_percent}%")
        if device.in_use_system_memory_bytes is not None:
            stats.append(f"统一内存使用 {format_bytes(device.in_use_system_memory_bytes)}")
        if device.allocated_system_memory_bytes is not None:
            stats.append(f"统一内存分配 {format_bytes(device.allocated_system_memory_bytes)}")
        if stats:
            lines.append("    " + " | ".join(stats))
        if device.last_submission_pid is not None:
            process_text = f" ({device.last_submission_process})" if device.last_submission_process else ""
            lines.append(f"    最近 GPU 提交: PID {device.last_submission_pid}{process_text}")
        for note in device.notes:
            lines.append(f"    注: {note}")
    return [fit_line(line, width) for line in lines]


def render_tui_actions(snapshot: MemorySnapshot, width: int) -> list[str]:
    lines = ["优化指令"]
    for index, action in enumerate(build_optimization_plan(snapshot), start=1):
        lines.append(f"{index}. [{action.risk}] {action.title}")
        lines.append(f"   $ {action.command}")
        lines.append(f"   {action.reason}")
        lines.append("")
    return lines or ["优化指令", "  暂无建议。"]


def init_tui_colors(curses_module: object) -> None:
    try:
        if not curses_module.has_colors():
            return
        curses_module.start_color()
        curses_module.use_default_colors()
        curses_module.init_pair(1, curses_module.COLOR_GREEN, -1)
        curses_module.init_pair(2, curses_module.COLOR_YELLOW, -1)
        curses_module.init_pair(3, curses_module.COLOR_RED, -1)
        curses_module.init_pair(4, curses_module.COLOR_CYAN, -1)
    except Exception:
        return


def draw_tui_frame(stdscr: object, curses_module: object, frame: TuiFrame) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    for row, line in enumerate(frame.lines[:height]):
        attr = tui_attr_for_line(line, curses_module)
        safe_addstr(stdscr, row, 0, fit_line(line, width), attr)
    stdscr.refresh()


def tui_attr_for_line(line: str, curses_module: object) -> int:
    try:
        if "CRIT" in line or "危险" in line or "HOT" in line:
            return curses_module.color_pair(3) | curses_module.A_BOLD
        if "WARN" in line or "偏紧" in line:
            return curses_module.color_pair(2) | curses_module.A_BOLD
        if "OK" in line or "正常" in line:
            return curses_module.color_pair(1)
        if line.startswith("mem TUI") or line.startswith("[") or line in {"软件活跃度", "进程明细", "显卡/GPU", "优化指令"}:
            return curses_module.A_BOLD
        if line.startswith("Tab/"):
            return curses_module.color_pair(4)
    except Exception:
        return 0
    return 0


def safe_addstr(stdscr: object, row: int, col: int, text: str, attr: int) -> None:
    try:
        height, width = stdscr.getmaxyx()
        if row >= height or col >= width:
            return
        stdscr.addstr(row, col, truncate(text, max(width - col - 1, 0)), attr)
    except Exception:
        return


def strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", value)


def terminalize_advice_text(value: str) -> str:
    lines: list[str] = []
    in_fence = False
    shell_fence = False

    for raw_line in value.splitlines():
        line = raw_line.rstrip()
        fence = re.match(r"^\s*```([A-Za-z0-9_-]*)\s*$", line)
        if fence:
            in_fence = not in_fence
            language = fence.group(1).lower()
            shell_fence = in_fence and language in {"", "bash", "sh", "shell", "zsh"}
            continue

        if in_fence:
            if not line.strip():
                append_advice_line(lines, "")
                continue
            prefix = "  $ " if shell_fence and not line.lstrip().startswith("$") else "  "
            append_advice_line(lines, normalize_mem_command_text(prefix + line.strip()))
            continue

        line = re.sub(r"`([^`]+)`", r"\1", line)
        append_advice_line(lines, normalize_mem_command_text(line))

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def append_advice_line(lines: list[str], line: str) -> None:
    if not line.strip() and (not lines or not lines[-1].strip()):
        return
    lines.append(line)


def normalize_mem_command_text(line: str) -> str:
    replacements = (
        (r"\bmem\s+ai\s+--ai-cli\b", "mem ai cli"),
        (r"\bmem\s+ai\s+--ai-timeout\b", "mem ai timeout"),
        (r"\bmem\s+ai\s+--top\b", "mem ai top"),
        (r"\bmem\s+--top\b", "mem top"),
        (r"\bmem\s+--watch\b", "mem watch"),
        (r"\bmem\s+--json\b", "mem json"),
        (r"\bmem\s+--no-processes\b", "mem no processes"),
        (r"\bmem\s+--no-guide\b", "mem no guide"),
    )
    normalized = line
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def render_text(snapshot: MemorySnapshot, show_processes: bool = True) -> str:
    terminal_width = shutil.get_terminal_size((100, 24)).columns
    bar_width = max(14, min(30, terminal_width - 60))
    lines: list[str] = []

    lines.extend(render_header(snapshot, width=terminal_width))
    lines.extend(render_health_panel(snapshot, width=terminal_width))
    lines.append("")
    lines.extend(render_pressure_panel(snapshot, width=terminal_width))

    lines.append("")
    lines.append(section_title("内存分类", width=terminal_width))
    lines.append(f"  {pad('类别', 12)} {pad('用量', 10, align='right')} {pad('占比', 7, align='right')}  {pad('图示', bar_width + 2)}  说明")
    for category in snapshot.categories:
        lines.append(
            f"  {pad(category.label, 12)} {pad(format_bytes(category.bytes), 10, align='right')} "
            f"{pad(format_percent(category.bytes, snapshot.total_bytes), 7, align='right')}  "
            f"{bar(category.bytes, snapshot.total_bytes, width=bar_width)}  "
            f"{category.description}"
        )

    purgeable = snapshot.details.get("purgeable_bytes")
    stored_compressed = snapshot.details.get("stored_compressed_bytes")
    detail_bits: list[str] = []
    if isinstance(purgeable, int) and purgeable > 0:
        detail_bits.append(f"可清理 {format_bytes(purgeable)}")
    if isinstance(stored_compressed, int) and stored_compressed > 0:
        detail_bits.append(f"压缩前逻辑数据 {format_bytes(stored_compressed)}")
    if detail_bits:
        lines.append("  " + " | ".join(detail_bits))

    if snapshot.graphics:
        lines.append("")
        lines.append(section_title("显卡/GPU", width=terminal_width))
        for device in snapshot.graphics:
            lines.append(f"  {device.name}")
            facts = []
            if device.device_type:
                facts.append(device.device_type)
            if device.vendor:
                facts.append(device.vendor)
            if device.cores is not None:
                facts.append(f"{device.cores} cores")
            if device.metal:
                facts.append(device.metal)
            if device.vram_bytes is not None:
                facts.append(f"VRAM {format_bytes(device.vram_bytes)}")
            if facts:
                lines.append("    " + " | ".join(facts))
            if device.displays:
                lines.append("    显示器: " + ", ".join(device.displays))
            gpu_stats = []
            if device.utilization_percent is not None:
                gpu_stats.append(f"设备利用率 {device.utilization_percent}%")
            if device.renderer_utilization_percent is not None:
                gpu_stats.append(f"Renderer {device.renderer_utilization_percent}%")
            if device.tiler_utilization_percent is not None:
                gpu_stats.append(f"Tiler {device.tiler_utilization_percent}%")
            if device.allocated_system_memory_bytes is not None:
                gpu_stats.append(f"已分配统一内存 {format_bytes(device.allocated_system_memory_bytes)}")
            if device.in_use_system_memory_bytes is not None:
                gpu_stats.append(f"正在使用统一内存 {format_bytes(device.in_use_system_memory_bytes)}")
            if device.in_use_driver_memory_bytes is not None:
                gpu_stats.append(f"驱动占用 {format_bytes(device.in_use_driver_memory_bytes)}")
            if gpu_stats:
                lines.append("    " + " | ".join(gpu_stats))
            if device.last_submission_pid is not None:
                process_text = f" ({device.last_submission_process})" if device.last_submission_process else ""
                lines.append(f"    最近 GPU 提交: PID {device.last_submission_pid}{process_text}")
            for note in device.notes:
                lines.append(f"    注: {note}")

    if show_processes and snapshot.software:
        lines.append("")
        lines.append(section_title("软件活跃度", width=terminal_width))
        lines.append(
            f"  {pad('风险', 5)} {pad('RSS', 10, align='right')} {pad('VSZ', 10, align='right')} "
            f"{pad('CPU', 7, align='right')} {pad('进程', 5, align='right')} "
            f"{pad('活跃', 5, align='right')} {pad('Top PID', 7, align='right')}  软件"
        )
        for item in snapshot.software:
            name_width = max(24, terminal_width - 62)
            name = pad(item.name, name_width)
            risk = software_risk(item, snapshot.total_bytes)
            lines.append(
                f"  {pad(risk, 5)} {pad(format_bytes(item.rss_bytes), 10, align='right')} "
                f"{pad(format_bytes(item.vsize_bytes), 10, align='right')} "
                f"{pad(f'{item.cpu_percent:.1f}%', 7, align='right')} {pad(str(item.process_count), 5, align='right')} "
                f"{pad(str(item.active_process_count), 5, align='right')} {pad(str(item.top_pid), 7, align='right')}  {name.rstrip()}"
            )

    if show_processes and snapshot.processes:
        lines.append("")
        lines.append(section_title("进程明细", width=terminal_width))
        lines.append(
            f"  {pad('PID', 7, align='right')} {pad('PPID', 7, align='right')} "
            f"{pad('RSS', 10, align='right')} {pad('VSZ', 10, align='right')} "
            f"{pad('MEM%', 6, align='right')} {pad('CPU%', 6, align='right')} "
            f"{pad('状态', 5, align='right')} {pad('软件', 18)}  进程"
        )
        for process in snapshot.processes:
            software = pad(process.software or software_name(process.command), 18)
            name = truncate(display_command(process.command), max(24, terminal_width - 84))
            lines.append(
                f"  {pad(str(process.pid), 7, align='right')} {pad(str(process.ppid), 7, align='right')} "
                f"{pad(format_bytes(process.rss_bytes), 10, align='right')} "
                f"{pad(format_bytes(process.vsize_bytes), 10, align='right')} "
                f"{pad(f'{process.memory_percent:.1f}%', 6, align='right')} "
                f"{pad(f'{process.cpu_percent:.1f}%', 6, align='right')} "
                f"{pad(process.state, 5, align='right')} {software}  {name}"
            )

    return "\n".join(lines)


def render_header(snapshot: MemorySnapshot, width: int) -> list[str]:
    status = overall_status(snapshot)
    title = f"mem {__version__} | {snapshot.platform} | 健康: {status}"
    return [title, "=" * min(width, max(60, len(title)))]


def render_health_panel(snapshot: MemorySnapshot, width: int, include_header: bool = True) -> list[str]:
    bar_width = max(14, min(28, width - 64))
    rows: list[str] = []
    if include_header:
        rows.append(section_title("内存概览", width=width))

    used_ratio = ratio(snapshot.used_bytes, snapshot.total_bytes)
    available_ratio = ratio(snapshot.available_bytes, snapshot.total_bytes)
    rows.append(
        metric_row(
            "内存",
            status_for_ratio(used_ratio, warn=0.80, critical=0.90),
            format_bytes(snapshot.used_bytes),
            format_bytes(snapshot.total_bytes),
            used_ratio,
            f"可用 {format_bytes(snapshot.available_bytes)} ({format_percent(snapshot.available_bytes, snapshot.total_bytes)})",
            bar_width,
        )
    )

    if snapshot.swap_total_bytes is not None and snapshot.swap_used_bytes is not None:
        swap_ratio = ratio(snapshot.swap_used_bytes, snapshot.swap_total_bytes)
        rows.append(
            metric_row(
                "交换区",
                status_for_ratio(swap_ratio, warn=0.50, critical=0.80),
                format_bytes(snapshot.swap_used_bytes),
                format_bytes(snapshot.swap_total_bytes),
                swap_ratio,
                "高交换区通常意味着卡顿风险",
                bar_width,
            )
        )

    gpu = primary_gpu(snapshot)
    if gpu and gpu.utilization_percent is not None:
        gpu_ratio = gpu.utilization_percent / 100
        rows.append(
            metric_row(
                "GPU",
                status_for_ratio(gpu_ratio, warn=0.60, critical=0.85),
                f"{gpu.utilization_percent}%",
                "100%",
                gpu_ratio,
                f"{gpu.name}, 统一内存 {format_bytes(gpu.in_use_system_memory_bytes)} / {format_bytes(gpu.allocated_system_memory_bytes)}",
                bar_width,
            )
        )

    pressure_free = snapshot.details.get("pressure_free_percent")
    if isinstance(pressure_free, int):
        pressure_used = max(0, min(100, 100 - pressure_free))
        rows.append(
            metric_row(
                "内存压力",
                status_for_ratio(pressure_used / 100, warn=0.65, critical=0.85),
                f"{pressure_used}%",
                "100%",
                pressure_used / 100,
                f"系统空闲比例 {pressure_free}%",
                bar_width,
            )
        )
    return rows


def render_pressure_panel(snapshot: MemorySnapshot, width: int) -> list[str]:
    lines = [section_title("诊断优先级", width=width)]
    findings = diagnosis_findings(snapshot)
    if not findings:
        lines.append("  OK    当前没有明显的内存/GPU压力信号。")
        return lines
    for severity, text in findings:
        lines.append(f"  {severity:<5} {text}")
    return lines


def diagnosis_findings(snapshot: MemorySnapshot) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    used_ratio = ratio(snapshot.used_bytes, snapshot.total_bytes)
    if used_ratio >= 0.90:
        findings.append(("CRIT", f"内存已用 {format_percent(snapshot.used_bytes, snapshot.total_bytes)}，优先减少活跃应用。"))
    elif used_ratio >= 0.80:
        findings.append(("WARN", f"内存已用 {format_percent(snapshot.used_bytes, snapshot.total_bytes)}，建议查看 RSS 最高的软件。"))

    if snapshot.swap_total_bytes and snapshot.swap_used_bytes:
        swap_ratio = ratio(snapshot.swap_used_bytes, snapshot.swap_total_bytes)
        if swap_ratio >= 0.80:
            findings.append(("CRIT", f"交换区 {format_percent(snapshot.swap_used_bytes, snapshot.swap_total_bytes)}，这是最容易导致卡顿的信号。"))
        elif swap_ratio >= 0.50:
            findings.append(("WARN", f"交换区 {format_percent(snapshot.swap_used_bytes, snapshot.swap_total_bytes)}，持续增长时应重启高内存应用。"))

    gpu = primary_gpu(snapshot)
    if gpu and gpu.utilization_percent is not None:
        if gpu.utilization_percent >= 85:
            findings.append(("CRIT", f"GPU 利用率 {gpu.utilization_percent}%，需要用 powermetrics 定位进程级 GPU 活跃度。"))
        elif gpu.utilization_percent >= 60:
            findings.append(("WARN", f"GPU 利用率 {gpu.utilization_percent}%，如果界面卡顿可进一步采样。"))

    if snapshot.software:
        hot = snapshot.software[0]
        findings.append(("INFO", f"当前热点软件: {hot.name} | RSS {format_bytes(hot.rss_bytes)} | CPU {hot.cpu_percent:.1f}% | 进程 {hot.process_count} 个。"))
    return findings


def metric_row(label: str, status: str, used: str, total: str, used_ratio: float, note: str, bar_width: int) -> str:
    return (
        f"  {pad(label, 8)} {pad(status, 5)} {pad(used, 10, align='right')} / "
        f"{pad(total, 10)} {pad(format_ratio_percent(used_ratio), 7, align='right')}  "
        f"{bar_ratio(used_ratio, bar_width)}  {note}"
    )


def section_title(title: str, width: int = 100) -> str:
    prefix = f"[ {title} ]"
    line_width = max(display_width(prefix), min(width, 100))
    return prefix + " " + "-" * max(0, line_width - display_width(prefix) - 1)


def overall_status(snapshot: MemorySnapshot) -> str:
    used_ratio = ratio(snapshot.used_bytes, snapshot.total_bytes)
    swap_ratio = ratio(snapshot.swap_used_bytes, snapshot.swap_total_bytes)
    gpu = primary_gpu(snapshot)
    gpu_ratio = (gpu.utilization_percent / 100) if gpu and gpu.utilization_percent is not None else 0
    if used_ratio >= 0.90 or swap_ratio >= 0.80 or gpu_ratio >= 0.85:
        return "危险"
    if used_ratio >= 0.80 or swap_ratio >= 0.50 or gpu_ratio >= 0.60:
        return "偏紧"
    return "正常"


def software_risk(item: SoftwareActivity, total_bytes: int) -> str:
    rss_ratio = ratio(item.rss_bytes, total_bytes)
    if rss_ratio >= 0.10 or item.cpu_percent >= 80:
        return "HOT"
    if rss_ratio >= 0.04 or item.cpu_percent >= 20:
        return "WARN"
    return "OK"


def status_for_ratio(value: float, warn: float, critical: float) -> str:
    if value >= critical:
        return "CRIT"
    if value >= warn:
        return "WARN"
    return "OK"


def primary_gpu(snapshot: MemorySnapshot) -> GraphicsDevice | None:
    return snapshot.graphics[0] if snapshot.graphics else None


def ratio(value: int | None, total: int | None) -> float:
    if value is None or not total:
        return 0.0
    return max(0.0, min(value / total, 1.0))


def format_ratio_percent(value: float) -> str:
    return f"{max(0.0, min(value, 1.0)) * 100:.1f}%"


def bar_ratio(value: float, width: int = 24) -> str:
    return bar(int(max(0.0, min(value, 1.0)) * 1000), 1000, width=width)


def parse_vm_stat(text: str) -> tuple[dict[str, int], int]:
    page_size_match = re.search(r"page size of\s+(\d+)\s+bytes", text)
    if not page_size_match:
        raise MemoryCollectionError("cannot parse vm_stat page size")
    page_size = int(page_size_match.group(1))
    stats: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        number_match = re.search(r"([\d,]+)", raw_value)
        if not number_match:
            continue
        key = key.strip().strip('"').lower()
        stats[key] = int(number_match.group(1).replace(",", ""))
    return stats, page_size


def parse_darwin_swap(text: str) -> tuple[int | None, int | None]:
    total_match = re.search(r"total\s*=\s*([\d.]+)([KMGTP])", text)
    used_match = re.search(r"used\s*=\s*([\d.]+)([KMGTP])", text)
    if not total_match or not used_match:
        return None, None
    return parse_size_number(total_match.group(1), total_match.group(2)), parse_size_number(
        used_match.group(1), used_match.group(2)
    )


def parse_memory_pressure_free_percent(text: str) -> int | None:
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", text)
    if not match:
        return None
    return int(match.group(1))


def parse_linux_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        match = re.search(r"(\d+)", raw_value)
        if match:
            values[key] = int(match.group(1)) * BYTES_PER_KIB
    return values


def collect_processes(limit: int | None) -> list[ProcessMemory]:
    if limit == 0:
        return []
    text = run_command(["ps", "-axo", "pid=,ppid=,rss=,vsz=,pcpu=,pmem=,state=,comm="], check=False)
    processes: list[ProcessMemory] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 7)
        if len(parts) < 8:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            rss_kib = int(parts[2])
            vsize_kib = int(parts[3])
            cpu = float(parts[4])
            memory = float(parts[5])
        except ValueError:
            continue
        command = parts[7]
        processes.append(
            ProcessMemory(
                pid=pid,
                ppid=ppid,
                rss_bytes=rss_kib * BYTES_PER_KIB,
                vsize_bytes=vsize_kib * BYTES_PER_KIB,
                cpu_percent=cpu,
                memory_percent=memory,
                state=parts[6],
                software=software_name(command),
                command=command,
            )
        )
    processes.sort(key=lambda item: item.rss_bytes, reverse=True)
    if limit is None:
        return processes
    return processes[:limit]


def limit_processes(processes: list[ProcessMemory], limit: int | None) -> list[ProcessMemory]:
    if limit == 0:
        return []
    if limit is None:
        return processes
    return processes[:limit]


def summarize_software(processes: list[ProcessMemory], limit: int | None) -> list[SoftwareActivity]:
    grouped: dict[str, list[ProcessMemory]] = {}
    for process in processes:
        grouped.setdefault(process.software or software_name(process.command), []).append(process)

    activities: list[SoftwareActivity] = []
    for name, items in grouped.items():
        items_by_rss = sorted(items, key=lambda item: item.rss_bytes, reverse=True)
        activities.append(
            SoftwareActivity(
                name=name,
                process_count=len(items),
                active_process_count=sum(1 for item in items if is_active_process(item)),
                rss_bytes=sum(item.rss_bytes for item in items),
                vsize_bytes=sum(item.vsize_bytes for item in items),
                cpu_percent=sum(item.cpu_percent for item in items),
                top_pid=items_by_rss[0].pid,
            )
        )
    activities.sort(key=lambda item: (item.rss_bytes, item.cpu_percent), reverse=True)
    if limit is None:
        return activities
    return activities[:limit]


def collect_darwin_graphics(processes: list[ProcessMemory]) -> list[GraphicsDevice]:
    profiler_text = run_command(["system_profiler", "SPDisplaysDataType"], check=False, timeout=8)
    devices = parse_darwin_display_devices(profiler_text)
    ioreg_text = run_command(["ioreg", "-r", "-c", "AGXAccelerator", "-d", "1"], check=False, timeout=5)
    performance = parse_ioreg_performance_statistics(ioreg_text)
    agc = parse_ioreg_agc_info(ioreg_text)

    last_pid = agc.get("fLastSubmissionPID")
    process_by_pid = {process.pid: process for process in processes}
    last_process = process_by_pid.get(last_pid).software if last_pid in process_by_pid else None

    notes = [
        "macOS 普通权限可读取 GPU 硬件、整体利用率和统一内存统计；进程级 GPU 占用通常需要 sudo powermetrics。",
    ]
    if not devices and (performance or agc):
        devices = [
            GraphicsDevice(
                name="Apple GPU",
                device_type="GPU",
                vendor=None,
                cores=None,
                metal=None,
                vram_bytes=None,
                displays=[],
                utilization_percent=None,
                renderer_utilization_percent=None,
                tiler_utilization_percent=None,
                allocated_system_memory_bytes=None,
                in_use_system_memory_bytes=None,
                in_use_driver_memory_bytes=None,
                last_submission_pid=None,
                last_submission_process=None,
                notes=[],
            )
        ]

    if not devices:
        return []

    enriched: list[GraphicsDevice] = []
    for index, device in enumerate(devices):
        enriched.append(
            GraphicsDevice(
                name=device.name,
                device_type=device.device_type,
                vendor=device.vendor,
                cores=device.cores,
                metal=device.metal,
                vram_bytes=device.vram_bytes,
                displays=device.displays,
                utilization_percent=performance.get("Device Utilization %") if index == 0 else None,
                renderer_utilization_percent=performance.get("Renderer Utilization %") if index == 0 else None,
                tiler_utilization_percent=performance.get("Tiler Utilization %") if index == 0 else None,
                allocated_system_memory_bytes=performance.get("Alloc system memory") if index == 0 else None,
                in_use_system_memory_bytes=performance.get("In use system memory") if index == 0 else None,
                in_use_driver_memory_bytes=performance.get("In use system memory (driver)") if index == 0 else None,
                last_submission_pid=last_pid if index == 0 else None,
                last_submission_process=last_process if index == 0 else None,
                notes=notes if index == 0 else [],
            )
        )
    return enriched


def collect_linux_graphics() -> list[GraphicsDevice]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return []
    text = run_command(
        [
            nvidia_smi,
            "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        timeout=5,
    )
    devices: list[GraphicsDevice] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            continue
        total = safe_int(parts[2])
        used = safe_int(parts[3])
        utilization = safe_int(parts[4])
        devices.append(
            GraphicsDevice(
                name=parts[0],
                device_type="GPU",
                vendor=f"NVIDIA driver {parts[1]}" if parts[1] else "NVIDIA",
                cores=None,
                metal=None,
                vram_bytes=total * BYTES_PER_MIB if total is not None else None,
                displays=[],
                utilization_percent=utilization,
                renderer_utilization_percent=None,
                tiler_utilization_percent=None,
                allocated_system_memory_bytes=total * BYTES_PER_MIB if total is not None else None,
                in_use_system_memory_bytes=used * BYTES_PER_MIB if used is not None else None,
                in_use_driver_memory_bytes=None,
                last_submission_pid=None,
                last_submission_process=None,
                notes=[],
            )
        )
    return devices


def parse_darwin_display_devices(text: str) -> list[GraphicsDevice]:
    devices: list[GraphicsDevice] = []
    current: dict[str, object] | None = None
    in_displays = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped == "Graphics/Displays:":
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 4 and stripped.endswith(":"):
            if current is not None:
                devices.append(graphics_device_from_profiler(current))
            current = {"name": stripped[:-1], "displays": []}
            in_displays = False
            continue
        if current is None:
            continue
        if stripped == "Displays:":
            in_displays = True
            continue
        if in_displays and indent == 8 and stripped.endswith(":"):
            displays = current.setdefault("displays", [])
            if isinstance(displays, list):
                displays.append(stripped[:-1])
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        value = value.strip()
        if key == "Chipset Model":
            current["name"] = value
        elif key == "Type":
            current["device_type"] = value
        elif key == "Vendor":
            current["vendor"] = value
        elif key == "Total Number of Cores":
            current["cores"] = safe_int(value)
        elif key == "Metal Support":
            current["metal"] = value
        elif key in {"VRAM", "VRAM (Total)"}:
            current["vram_bytes"] = parse_human_size(value)

    if current is not None:
        devices.append(graphics_device_from_profiler(current))
    return devices


def graphics_device_from_profiler(values: dict[str, object]) -> GraphicsDevice:
    return GraphicsDevice(
        name=str(values.get("name") or "Unknown GPU"),
        device_type=optional_str(values.get("device_type")),
        vendor=optional_str(values.get("vendor")),
        cores=optional_int(values.get("cores")),
        metal=optional_str(values.get("metal")),
        vram_bytes=optional_int(values.get("vram_bytes")),
        displays=list(values.get("displays") or []),
        utilization_percent=None,
        renderer_utilization_percent=None,
        tiler_utilization_percent=None,
        allocated_system_memory_bytes=None,
        in_use_system_memory_bytes=None,
        in_use_driver_memory_bytes=None,
        last_submission_pid=None,
        last_submission_process=None,
        notes=[],
    )


def parse_ioreg_performance_statistics(text: str) -> dict[str, int]:
    match = re.search(r'"PerformanceStatistics"\s*=\s*\{([^}]*)\}', text)
    if not match:
        return {}
    return {key: int(value) for key, value in re.findall(r'"([^"]+)"\s*=\s*(\d+)', match.group(1))}


def parse_ioreg_agc_info(text: str) -> dict[str, int]:
    match = re.search(r'"AGCInfo"\s*=\s*\{([^}]*)\}', text)
    if not match:
        return {}
    return {key: int(value) for key, value in re.findall(r'"([^"]+)"\s*=\s*(\d+)', match.group(1))}


def software_name(command: str) -> str:
    app_match = re.search(r"/([^/]+)\.app(?:/|$)", command)
    if app_match:
        return app_match.group(1)
    framework_match = re.search(r"/([^/]+)\.framework(?:/|$)", command)
    if framework_match:
        return framework_match.group(1)
    name = os.path.basename(command)
    return name or command


def is_active_process(process: ProcessMemory) -> bool:
    return process.cpu_percent >= 1.0 or process.state.startswith("R")


def safe_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None


def optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_human_size(value: str) -> int | None:
    match = re.search(r"([\d.]+)\s*([KMGTPE]?)(?:i?B|B|bytes)?", value, re.IGNORECASE)
    if not match:
        return None
    number, unit = match.group(1), match.group(2).upper()
    if not unit:
        return int(float(number))
    return parse_size_number(number, unit)


def run_command(command: list[str], check: bool = True, timeout: float | None = None) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if check:
            raise MemoryCollectionError(f"{command[0]} timed out") from exc
        return ""
    if check and completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"{command[0]} failed"
        raise MemoryCollectionError(message)
    return completed.stdout


def run_command_combined(command: list[str], timeout: float | None = None) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""
    return "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())


def pages_to_bytes(pages: int, page_size: int) -> int:
    return int(pages * page_size)


def parse_size_number(number: str, unit: str) -> int:
    multiplier = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
        "E": 1024**6,
    }[unit.upper()]
    return int(float(number) * multiplier)


def format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    size = float(value)
    unit = units[0]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    if abs(size) >= 100:
        return f"{size:.0f} {unit}"
    if abs(size) >= 10:
        return f"{size:.1f} {unit}"
    return f"{size:.2f} {unit}"


def format_percent(value: int | None, total: int | None) -> str:
    if value is None or not total:
        return "-"
    return f"{value / total * 100:.1f}%"


def bar(value: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return "[" + "-" * width + "]"
    filled = round(max(0, min(value / total, 1)) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def display_command(command: str) -> str:
    name = os.path.basename(command)
    return name or command


def pad(value: object, width: int, align: str = "left") -> str:
    text = truncate(str(value), width)
    padding = max(width - display_width(text), 0)
    if align == "right":
        return " " * padding + text
    return text + " " * padding


def fit_line(value: str, width: int) -> str:
    if width <= 0:
        return ""
    return truncate(value, width)


def truncate(value: str, width: int) -> str:
    if width <= 1:
        return value[:width]
    if display_width(value) <= width:
        return value
    if width <= 3:
        return truncate_display(value, width)
    return truncate_display(value, width - 3) + "..."


def truncate_display(value: str, width: int) -> str:
    output: list[str] = []
    current = 0
    for char in value:
        char_width = char_display_width(char)
        if current + char_width > width:
            break
        output.append(char)
        current += char_width
    return "".join(output)


def display_width(value: str) -> int:
    return sum(char_display_width(char) for char in value)


def char_display_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    if unicodedata.category(char) in {"Cc", "Cf"}:
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
