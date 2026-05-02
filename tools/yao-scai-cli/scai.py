#!/usr/bin/env python3
from __future__ import annotations

import argparse
import curses
import heapq
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_SCAN_ROOT = Path.cwd()
DEFAULT_LIMIT = 20
DEFAULT_BRIEF_LIMIT = 50
DEFAULT_MORE_LIMIT = 100
DEFAULT_ANALYSIS_LIMIT = 80
COMPUTER_SCAN_ROOT = Path("/")
COMPRESSED_SUFFIXES = {".gz", ".bz2", ".xz", ".zip", ".zst"}
ARCHIVE_SUFFIXES = {".7z", ".bz2", ".dmg", ".gz", ".iso", ".rar", ".tar", ".tgz", ".xz", ".zip", ".zst"}
MEDIA_SUFFIXES = {
    ".avi",
    ".m4a",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".wav",
    ".webm",
    ".mkv",
    ".heic",
    ".jpg",
    ".jpeg",
    ".png",
    ".psd",
}
DOCUMENT_SUFFIXES = {".doc", ".docx", ".key", ".numbers", ".pages", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx"}
DATA_SUFFIXES = {".csv", ".db", ".dump", ".json", ".parquet", ".sqlite", ".sql"}
DEV_CACHE_NAMES = {
    ".cache",
    ".gradle",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
}
BACKUP_MARKERS = {"backup", "backups", "bak", "old", "archive", "archives", "备份", "归档"}
DOWNLOAD_MARKERS = {"download", "downloads", "下载"}
COMMAND_ALIASES = {
    "brief": "brief",
    "b": "brief",
    "top": "top",
    "file": "top",
    "files": "top",
    "f": "top",
    "dir": "dirs",
    "dirs": "dirs",
    "d": "dirs",
    "tui": "tui",
    "ui": "tui",
    "t": "tui",
    "explain": "explain",
    "why": "explain",
    "x": "explain",
    "plan": "plan",
    "p": "plan",
    "more": "more",
    "m": "more",
    "ai": "ai",
}
COMPUTER_ROOT_ALIASES = {"all", "c", "computer", "mac", "root", "全盘", "电脑", "根目录"}
OPTIONS_REQUIRING_VALUE = {"--limit", "--max-depth", "--mode", "--timeout"}
TUI_ALIASES: set[str] = set()
PLAIN_ALIASES: set[str] = set()
DEFAULT_EXCLUDED_DIR_NAMES = {
    ".Trash",
    ".Spotlight-V100",
    ".fseventsd",
    ".TemporaryItems",
    ".DocumentRevisions-V100",
    "Library",
    ".cache",
    ".npm",
    ".pnpm-store",
    ".yarn",
    ".bun",
    ".rustup",
    ".cargo",
    ".nvm",
    ".codex",
    ".gradle",
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    ".turbo",
}
SYSTEM_ROOT_PREFIXES = (
    "/System",
    "/Library",
    "/Applications",
    "/private",
    "/Volumes",
    "/dev",
    "/bin",
    "/sbin",
    "/usr",
    "/opt",
    "/cores",
)
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_CYAN = "\033[36m"
RISKY_SYSTEM_PREFIXES = (
    "/System",
    "/Library",
    "/Applications",
    "/dev",
    "/bin",
    "/sbin",
    "/usr",
    "/opt",
    "/cores",
)


@dataclass(order=True)
class FileRecord:
    size: int
    mtime: float
    sort_path: str = field(compare=True)
    path: Path = field(compare=False)


@dataclass(order=True)
class DirectoryRecord:
    size: int
    mtime: float
    file_count: int
    sort_path: str = field(compare=True)
    path: Path = field(compare=False)


@dataclass
class ScanStats:
    scanned_files: int = 0
    scanned_dirs: int = 0
    skipped_dirs: int = 0
    skipped_entries: int = 0


@dataclass
class Insight:
    path: Path
    size: int
    kind: str
    risk: str
    category: str
    reason: str
    action: str


@dataclass
class SpaceAnalysis:
    root: Path
    files: list[FileRecord]
    dirs: list[DirectoryRecord]
    file_stats: ScanStats
    dir_stats: ScanStats
    elapsed: float
    insights: list[Insight]


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def infer_format(path: Path) -> str:
    suffixes = path.suffixes
    if not suffixes:
        return "无扩展名"
    if len(suffixes) >= 2 and suffixes[-1].lower() in COMPRESSED_SUFFIXES:
        return "".join(suffixes[-2:]).lstrip(".").lower()
    return suffixes[-1].lstrip(".").lower()


def format_mtime(timestamp: float) -> str:
    if timestamp <= 0:
        return "-"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def truncate_middle(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    left = (width - 1) // 2
    right = width - left - 1
    return f"{text[:left]}…{text[-right:]}"


def should_skip_dir(path: Path, root: Path, include_all: bool) -> bool:
    if include_all or path == root:
        return False

    path_str = str(path)
    if root == COMPUTER_SCAN_ROOT and any(path_str == prefix or path_str.startswith(prefix + os.sep) for prefix in SYSTEM_ROOT_PREFIXES):
        return True

    return path.name in DEFAULT_EXCLUDED_DIR_NAMES


def push_top_record(heap: list[object], record: object, limit: int) -> None:
    if len(heap) < limit:
        heapq.heappush(heap, record)
        return
    if record > heap[0]:
        heapq.heapreplace(heap, record)


def scan_top_files(root: Path, limit: int, include_all: bool) -> tuple[list[FileRecord], ScanStats]:
    stats = ScanStats()
    heap: list[FileRecord] = []

    if root.is_file():
        stat = root.stat()
        push_top_record(
            heap,
            FileRecord(size=stat.st_size, mtime=stat.st_mtime, sort_path=str(root), path=root),
            limit,
        )
        stats.scanned_files = 1
        return sorted(heap, reverse=True), stats

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                stats.scanned_dirs += 1
                for entry in iterator:
                    try:
                        entry_path = Path(entry.path)

                        if entry.is_symlink():
                            stats.skipped_entries += 1
                            continue

                        if entry.is_dir(follow_symlinks=False):
                            if should_skip_dir(entry_path, root, include_all):
                                stats.skipped_dirs += 1
                                continue
                            stack.append(entry_path)
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            stats.skipped_entries += 1
                            continue

                        stat = entry.stat(follow_symlinks=False)
                        push_top_record(
                            heap,
                            FileRecord(
                                size=stat.st_size,
                                mtime=stat.st_mtime,
                                sort_path=str(entry_path),
                                path=entry_path,
                            ),
                            limit,
                        )
                        stats.scanned_files += 1
                    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                        stats.skipped_entries += 1
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            stats.skipped_entries += 1

    return sorted(heap, reverse=True), stats


def scan_top_dirs(
    root: Path,
    limit: int,
    include_all: bool,
    max_depth: int | None = None,
) -> tuple[list[DirectoryRecord], ScanStats]:
    stats = ScanStats()
    visit_order: list[Path] = []
    children_map: dict[Path, list[Path]] = {}
    depth_map: dict[Path, int] = {}
    direct_sizes: dict[Path, int] = {}
    direct_mtimes: dict[Path, float] = {}
    direct_file_counts: dict[Path, int] = {}
    aggregated: dict[Path, DirectoryRecord] = {}
    heap: list[DirectoryRecord] = []

    stack = [(root, 0)]
    while stack:
        current, current_depth = stack.pop()
        visit_order.append(current)
        depth_map[current] = current_depth
        children: list[Path] = []
        direct_size = 0
        direct_mtime = 0.0
        direct_file_count = 0

        try:
            with os.scandir(current) as iterator:
                stats.scanned_dirs += 1
                for entry in iterator:
                    try:
                        entry_path = Path(entry.path)

                        if entry.is_symlink():
                            stats.skipped_entries += 1
                            continue

                        if entry.is_dir(follow_symlinks=False):
                            if should_skip_dir(entry_path, root, include_all):
                                stats.skipped_dirs += 1
                                continue
                            children.append(entry_path)
                            stack.append((entry_path, current_depth + 1))
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            stats.skipped_entries += 1
                            continue

                        stat = entry.stat(follow_symlinks=False)
                        direct_size += stat.st_size
                        direct_mtime = max(direct_mtime, stat.st_mtime)
                        direct_file_count += 1
                        stats.scanned_files += 1
                    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                        stats.skipped_entries += 1
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            stats.skipped_entries += 1
            children_map[current] = children
            direct_sizes[current] = direct_size
            direct_mtimes[current] = direct_mtime
            direct_file_counts[current] = direct_file_count
            continue

        children_map[current] = children
        direct_sizes[current] = direct_size
        direct_mtimes[current] = direct_mtime
        direct_file_counts[current] = direct_file_count

    for current in reversed(visit_order):
        total_size = direct_sizes[current]
        latest_mtime = direct_mtimes[current]
        total_file_count = direct_file_counts[current]

        for child in children_map[current]:
            child_record = aggregated[child]
            total_size += child_record.size
            latest_mtime = max(latest_mtime, child_record.mtime)
            total_file_count += child_record.file_count

        current_record = DirectoryRecord(
            size=total_size,
            mtime=latest_mtime,
            file_count=total_file_count,
            sort_path=str(current),
            path=current,
        )
        aggregated[current] = current_record

        current_depth = depth_map[current]
        if current == root:
            continue
        if max_depth is not None and current_depth > max_depth:
            continue
        push_top_record(heap, current_record, limit)

    return sorted(heap, reverse=True), stats


def display_name(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
        return str(relative)
    except ValueError:
        return str(path)


def print_scan_summary(root: Path, stats: ScanStats, elapsed: float, include_all: bool) -> None:
    print(f"扫描范围: {root}")
    if include_all:
        print("扫描模式: 全量扫描，不跳过默认目录")
    else:
        excluded = ", ".join(sorted(DEFAULT_EXCLUDED_DIR_NAMES))
        print(f"默认排除: {excluded}")
    print(
        "统计信息: "
        f"目录 {stats.scanned_dirs} 个, "
        f"文件 {stats.scanned_files} 个, "
        f"跳过目录 {stats.skipped_dirs} 个, "
        f"其他跳过 {stats.skipped_entries} 个, "
        f"用时 {elapsed:.2f}s"
    )
    print()


def print_file_results(root: Path, records: list[FileRecord], stats: ScanStats, elapsed: float, include_all: bool) -> None:
    print_scan_summary(root=root, stats=stats, elapsed=elapsed, include_all=include_all)

    if not records:
        print("没有找到可展示的文件。")
        return

    terminal_width = shutil.get_terminal_size((120, 20)).columns
    fixed_width = 6 + 3 + 8 + 3 + 12 + 3 + 19
    name_width = max(28, min(80, terminal_width - fixed_width))
    header = f"{'编号':>4}  {'文件名':<{name_width}}  {'格式':<8}  {'大小':>10}  {'最近修改时间':<19}"
    print(header)
    print("-" * len(header))

    for index, record in enumerate(records, start=1):
        name = truncate_middle(display_name(record.path, root), name_width)
        fmt = truncate_middle(infer_format(record.path), 8)
        size = human_size(record.size)
        mtime = format_mtime(record.mtime)
        print(f"{index:>4}  {name:<{name_width}}  {fmt:<8}  {size:>10}  {mtime}")


def print_directory_results(
    root: Path,
    records: list[DirectoryRecord],
    stats: ScanStats,
    elapsed: float,
    include_all: bool,
) -> None:
    print_scan_summary(root=root, stats=stats, elapsed=elapsed, include_all=include_all)

    if not records:
        print("没有找到可展示的文件夹。")
        return

    terminal_width = shutil.get_terminal_size((130, 20)).columns
    fixed_width = 6 + 3 + 9 + 3 + 12 + 3 + 8 + 3 + 19
    name_width = max(28, min(78, terminal_width - fixed_width))
    header = f"{'编号':>4}  {'文件夹':<{name_width}}  {'总大小':>10}  {'文件数':>6}  {'最近修改时间':<19}"
    print(header)
    print("-" * len(header))

    for index, record in enumerate(records, start=1):
        name = truncate_middle(display_name(record.path, root), name_width)
        size = human_size(record.size)
        mtime = format_mtime(record.mtime)
        print(f"{index:>4}  {name:<{name_width}}  {size:>10}  {record.file_count:>6}  {mtime}")


def run_with_progress(message: str, work):
    if not sys.stderr.isatty():
        return work()

    result: list[object] = []
    errors: list[BaseException] = []

    def target() -> None:
        try:
            result.append(work())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    frames = "|/-\\"
    start = time.time()
    frame_index = 0

    while thread.is_alive():
        elapsed = time.time() - start
        line = f"{frames[frame_index % len(frames)]} {message} 用时 {elapsed:.1f}s"
        sys.stderr.write("\r" + truncate_middle(line, shutil.get_terminal_size((100, 20)).columns - 1))
        sys.stderr.flush()
        frame_index += 1
        time.sleep(0.12)

    thread.join()
    width = shutil.get_terminal_size((100, 20)).columns
    sys.stderr.write("\r" + " " * max(0, width - 1) + "\r")
    sys.stderr.flush()

    if errors:
        raise errors[0]
    return result[0] if result else None


def terminal_styles_enabled() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def terminal_style(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{code}{text}{ANSI_RESET}"


def render_inline_markdown(text: str, styles: bool) -> str:
    def render_code(match: re.Match[str]) -> str:
        return terminal_style(match.group(1), ANSI_CYAN, styles)

    def render_bold(match: re.Match[str]) -> str:
        return terminal_style(match.group(1), ANSI_BOLD, styles)

    def render_dim(match: re.Match[str]) -> str:
        return terminal_style(match.group(1), ANSI_DIM, styles)

    def render_link(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        url = match.group(2).strip()
        return url if label == url else f"{label} ({url})"

    text = re.sub(r"`([^`\n]+)`", render_code, text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", render_link, text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", render_bold, text)
    text = re.sub(r"__([^_\n]+)__", render_bold, text)
    text = re.sub(r"~~([^~\n]+)~~", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", render_dim, text)
    return text


def render_markdown_for_terminal(markdown: str) -> str:
    styles = terminal_styles_enabled()
    rendered: list[str] = []
    in_code_block = False

    for raw_line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()

        if stripped.startswith(("```", "~~~")):
            in_code_block = not in_code_block
            if rendered and rendered[-1]:
                rendered.append("")
            continue

        if in_code_block:
            rendered.append(f"    {raw_line.rstrip()}" if raw_line else "")
            continue

        if not stripped:
            if rendered and rendered[-1]:
                rendered.append("")
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            if rendered and rendered[-1]:
                rendered.append("")
            title = render_inline_markdown(heading.group(2).strip(), styles)
            rendered.append(terminal_style(title, ANSI_BOLD, styles))
            continue

        if re.match(r"^([-*_])(?:\s*\1){2,}$", stripped):
            width = shutil.get_terminal_size((80, 20)).columns
            rendered.append("-" * min(72, max(20, width - 8)))
            continue

        task = re.match(r"^(\s*)[-+*]\s+\[([ xX])\]\s+(.+)$", raw_line)
        if task:
            indent = " " * min(len(task.group(1)), 8)
            mark = "x" if task.group(2).lower() == "x" else " "
            rendered.append(f"{indent}[{mark}] {render_inline_markdown(task.group(3).strip(), styles)}")
            continue

        bullet = re.match(r"^(\s*)[-+*]\s+(.+)$", raw_line)
        if bullet:
            indent = " " * min(len(bullet.group(1)), 8)
            rendered.append(f"{indent}- {render_inline_markdown(bullet.group(2).strip(), styles)}")
            continue

        numbered = re.match(r"^(\s*)(\d+)[.)]\s+(.+)$", raw_line)
        if numbered:
            indent = " " * min(len(numbered.group(1)), 8)
            rendered.append(
                f"{indent}{numbered.group(2)}. {render_inline_markdown(numbered.group(3).strip(), styles)}"
            )
            continue

        quote = re.match(r"^>\s?(.*)$", stripped)
        if quote:
            rendered.append(f"  {render_inline_markdown(quote.group(1).strip(), styles)}")
            continue

        rendered.append(render_inline_markdown(raw_line.rstrip(), styles))

    return "\n".join(rendered).strip()


def parse_size(text: str) -> int:
    value = text.strip().lower()
    units = {
        "b": 1,
        "k": 1024,
        "kb": 1024,
        "m": 1024**2,
        "mb": 1024**2,
        "g": 1024**3,
        "gb": 1024**3,
        "t": 1024**4,
        "tb": 1024**4,
    }
    number = ""
    unit = ""
    for char in value:
        if char.isdigit() or char == ".":
            number += char
        elif not char.isspace():
            unit += char
    if not number:
        raise ValueError("size must include a number")
    multiplier = units.get(unit or "b")
    if multiplier is None:
        raise ValueError(f"unsupported size unit: {unit}")
    return int(float(number) * multiplier)


def risk_label(risk: str) -> str:
    return {
        "safe": "可安全关注",
        "review": "需要确认",
        "risky": "高风险",
    }.get(risk, risk)


def path_parts_lower(path: Path) -> set[str]:
    return {part.lower() for part in path.parts}


def looks_like_backup(path: Path) -> bool:
    lowered = str(path).lower()
    name = path.name.lower()
    return any(marker in lowered for marker in BACKUP_MARKERS) or name.endswith((".bak", ".old", ".backup"))


def classify_path(path: Path, size: int, kind: str) -> Insight:
    suffix = path.suffix.lower()
    parts = path_parts_lower(path)

    if any(str(path) == prefix or str(path).startswith(prefix + os.sep) for prefix in RISKY_SYSTEM_PREFIXES):
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="risky",
            category="系统或受管目录",
            reason="路径位于系统、应用或受管区域，清理风险高。",
            action="不要直接删除；只通过系统设置或对应应用管理。",
        )

    if parts & DEV_CACHE_NAMES:
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="safe",
            category="开发缓存/构建产物",
            reason="命中常见可重建目录，例如 node_modules、.next、dist、target 或缓存目录。",
            action="确认项目不在运行后，可优先清理或通过包管理器重建。",
        )

    if looks_like_backup(path):
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="review",
            category="历史备份/归档",
            reason="名称看起来像备份、旧版本或归档文件。",
            action="确认是否已有更新备份，再移动到废纸篓或外置存储。",
        )

    if suffix in ARCHIVE_SUFFIXES:
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="review",
            category="压缩包/镜像",
            reason="大压缩包或镜像通常是下载残留、安装包或一次性传输文件。",
            action="确认来源和是否已解压使用，再决定是否清理。",
        )

    if suffix in MEDIA_SUFFIXES:
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="review",
            category="大媒体文件",
            reason="图片、视频或音频文件通常体积大，但可能是个人素材。",
            action="人工确认后归档到外置盘或云端，不建议自动删除。",
        )

    if suffix in DATA_SUFFIXES:
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="review",
            category="数据/数据库文件",
            reason="数据文件、数据库或导出文件可能承载业务内容。",
            action="确认是否可再生成或已备份，再处理。",
        )

    if suffix in DOCUMENT_SUFFIXES:
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="review",
            category="文档资料",
            reason="文档可能包含人工产出或业务资料。",
            action="人工确认价值后再归档或删除。",
        )

    if parts & DOWNLOAD_MARKERS:
        return Insight(
            path=path,
            size=size,
            kind=kind,
            risk="review",
            category="下载目录残留",
            reason="下载目录常见临时安装包、素材和传输文件。",
            action="按文件名和修改时间确认是否仍需要。",
        )

    return Insight(
        path=path,
        size=size,
        kind=kind,
        risk="review",
        category="未分类大项",
        reason="Scai 还不能可靠判断用途。",
        action="先查看来源、修改时间和所属项目，再决定是否处理。",
    )


def build_insights(records: list[FileRecord | DirectoryRecord]) -> list[Insight]:
    insights: list[Insight] = []
    for record in records:
        kind = "dir" if isinstance(record, DirectoryRecord) else "file"
        insights.append(classify_path(record.path, record.size, kind))
    return sorted(insights, key=lambda item: item.size, reverse=True)


def aggregate_insights(insights: list[Insight], risk: str | None = None) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for insight in insights:
        if risk is not None and insight.risk != risk:
            continue
        totals[insight.category] = totals.get(insight.category, 0) + insight.size
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def create_space_analysis(root: Path, limit: int, include_all: bool, max_depth: int | None = 1) -> SpaceAnalysis:
    start = time.time()
    dir_limit = max(8, limit)
    file_limit = max(DEFAULT_ANALYSIS_LIMIT, limit)
    dirs, dir_stats = scan_top_dirs(root=root, limit=dir_limit, include_all=include_all, max_depth=max_depth)
    files, file_stats = scan_top_files(root=root, limit=file_limit, include_all=include_all)
    insights = build_insights([*dirs, *files])
    return SpaceAnalysis(
        root=root,
        files=files,
        dirs=dirs,
        file_stats=file_stats,
        dir_stats=dir_stats,
        elapsed=time.time() - start,
        insights=insights,
    )


def print_numbered_records(root: Path, records: list[FileRecord | DirectoryRecord], label: str, limit: int = 5) -> None:
    print(label)
    if not records:
        print("  暂无记录")
        return
    for index, record in enumerate(records[:limit], start=1):
        name = display_name(record.path, root)
        print(f"  {index}. {truncate_middle(name, 44):<44} {human_size(record.size):>10}")


def print_file_detail_records(root: Path, records: list[FileRecord], limit: int) -> None:
    shown = min(limit, len(records))
    print(f"Top {shown} 文件明细:")
    if not records:
        print("  暂无文件记录")
        return

    terminal_width = shutil.get_terminal_size((130, 20)).columns
    fixed_width = 6 + 3 + 12 + 3 + 10 + 3 + 16
    name_width = max(28, min(78, terminal_width - fixed_width))
    header = f"{'编号':>4}  {'大小':>10}  {'风险':<8}  {'分类':<14}  {'文件':<{name_width}}"
    print(header)
    print("-" * len(header))

    for index, record in enumerate(records[:limit], start=1):
        insight = classify_path(record.path, record.size, "file")
        name = truncate_middle(display_name(record.path, root), name_width)
        risk = truncate_middle(risk_label(insight.risk), 8)
        category = truncate_middle(insight.category, 14)
        print(f"{index:>4}  {human_size(record.size):>10}  {risk:<8}  {category:<14}  {name:<{name_width}}")


def print_aggregate_lines(items: list[tuple[str, int]], empty_text: str, limit: int = 5) -> None:
    if not items:
        print(f"  - {empty_text}")
        return
    for category, size in items[:limit]:
        print(f"  - {category}: 约 {human_size(size)}")


def run_brief(args: argparse.Namespace) -> int:
    root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
    analysis = run_with_progress(
        f"Scai 正在扫描 {root}",
        lambda: create_space_analysis(root=root, limit=args.limit, include_all=args.all, max_depth=1),
    )

    print("Scai Space Brief")
    print()
    print(f"扫描范围: {analysis.root}")
    print(f"扫描用时: {analysis.elapsed:.2f}s")
    print(
        "统计信息: "
        f"目录 {analysis.dir_stats.scanned_dirs} 个, "
        f"文件 {analysis.file_stats.scanned_files} 个, "
        f"跳过目录 {analysis.dir_stats.skipped_dirs + analysis.file_stats.skipped_dirs} 个"
    )
    print()

    primary_records: list[FileRecord | DirectoryRecord] = [*analysis.dirs] if analysis.dirs else [*analysis.files]
    print_numbered_records(analysis.root, primary_records, "主要占用:", limit=5)
    print()

    print("可安全关注:")
    print_aggregate_lines(aggregate_insights(analysis.insights, risk="safe"), "暂未发现明显可重建缓存或构建产物")
    print()

    print("需要确认:")
    print_aggregate_lines(aggregate_insights(analysis.insights, risk="review"), "暂未发现需要人工确认的大项")
    print()

    print_file_detail_records(analysis.root, analysis.files, args.limit)
    print()

    risky = [item for item in analysis.insights if item.risk == "risky"]
    if risky:
        print("高风险项:")
        for item in risky[:3]:
            print(f"  - {truncate_middle(display_name(item.path, analysis.root), 44)}: {item.reason}")
        print()

    print("显示更多:")
    print(f"  - scai more        显示 Top {DEFAULT_MORE_LIMIT} 文件")
    print("  - scai more 200    显示 Top 200 文件")
    print()

    print("下一步:")
    print("  - scai top          查看最大文件")
    print("  - scai dirs         查看最大文件夹")
    print("  - scai tui          进入交互浏览")
    print("  - scai plan 20g     生成释放空间方案")
    print("  - scai ai           生成 AI 诊断")
    return 0


def explain_path(path: Path, include_all: bool) -> Insight:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    if resolved.is_dir():
        summary = scan_path_summary(resolved, include_all=include_all)
        return classify_path(resolved, summary.size, "dir")
    stat = resolved.stat()
    return classify_path(resolved, stat.st_size, "file")


@dataclass
class PathSummary:
    size: int
    file_count: int
    dir_count: int
    mtime: float


def scan_path_summary(root: Path, include_all: bool) -> PathSummary:
    if root.is_file():
        stat = root.stat()
        return PathSummary(size=stat.st_size, file_count=1, dir_count=0, mtime=stat.st_mtime)

    total_size = 0
    file_count = 0
    dir_count = 0
    latest_mtime = 0.0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                dir_count += 1
                for entry in iterator:
                    try:
                        entry_path = Path(entry.path)
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if should_skip_dir(entry_path, root, include_all):
                                continue
                            stack.append(entry_path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        total_size += stat.st_size
                        file_count += 1
                        latest_mtime = max(latest_mtime, stat.st_mtime)
                    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                        continue
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            continue
    return PathSummary(size=total_size, file_count=file_count, dir_count=dir_count, mtime=latest_mtime)


def run_explain(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if path.is_dir():
        summary = run_with_progress(f"Scai 正在扫描 {path}", lambda: scan_path_summary(path, include_all=args.all))
        insight = classify_path(path, summary.size, "dir")
    else:
        summary = scan_path_summary(path, include_all=args.all)
        insight = explain_path(path, include_all=args.all)
    print("Scai Explain")
    print()
    print(f"路径: {insight.path}")
    print(f"类型: {'文件夹' if insight.kind == 'dir' else '文件'}")
    print(f"大小: {human_size(insight.size)}")
    if insight.kind == "dir":
        print(f"内容: 目录 {summary.dir_count} 个, 文件 {summary.file_count} 个")
    print(f"风险: {risk_label(insight.risk)}")
    print(f"分类: {insight.category}")
    print(f"判断: {insight.reason}")
    print(f"建议: {insight.action}")
    return 0


def select_plan_items(insights: list[Insight], target_bytes: int) -> tuple[list[Insight], int]:
    ordered = sorted(
        [item for item in insights if item.risk != "risky"],
        key=lambda item: (0 if item.risk == "safe" else 1, -item.size),
    )
    selected: list[Insight] = []
    total = 0
    for item in ordered:
        if any(paths_overlap(item.path, selected_item.path) for selected_item in selected):
            continue
        selected.append(item)
        total += item.size
        if total >= target_bytes:
            break
    return selected, total


def paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def run_plan(args: argparse.Namespace) -> int:
    root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
    try:
        target = parse_size(args.target)
    except ValueError as exc:
        print(f"目标大小无效: {exc}", file=sys.stderr)
        return 2

    analysis = run_with_progress(
        f"Scai 正在扫描 {root}",
        lambda: create_space_analysis(root=root, limit=args.limit, include_all=args.all, max_depth=None),
    )
    selected, total = select_plan_items(analysis.insights, target)

    print(f"Scai Reclaim Plan: {human_size(target)}")
    print()
    print(f"扫描范围: {root}")
    print("模式: 只生成计划，不删除任何文件。")
    print()
    if not selected:
        print("没有找到可用于生成计划的候选项。")
        return 0

    for index, item in enumerate(selected, start=1):
        relative = display_name(item.path, root)
        print(f"{index}. [{risk_label(item.risk)}] {human_size(item.size):>10}  {truncate_middle(relative, 58)}")
        print(f"   分类: {item.category}")
        print(f"   原因: {item.reason}")
        print(f"   建议: {item.action}")

    print()
    print(f"预计可处理空间: {human_size(total)}")
    if total < target:
        print("提示: 当前候选项不足以达到目标，可以扩大扫描范围或使用 --all。")
    print("安全策略: 后续执行清理时应默认移动到废纸篓，并记录操作日志。")
    return 0


def analysis_payload(analysis: SpaceAnalysis) -> dict[str, object]:
    return {
        "root": str(analysis.root),
        "elapsed_seconds": round(analysis.elapsed, 2),
        "top_dirs": [
            {"path": display_name(record.path, analysis.root), "size": record.size, "human_size": human_size(record.size)}
            for record in analysis.dirs[:12]
        ],
        "top_files": [
            {
                "path": display_name(record.path, analysis.root),
                "size": record.size,
                "human_size": human_size(record.size),
                "format": infer_format(record.path),
            }
            for record in analysis.files[:20]
        ],
        "insights": [
            {
                "path": display_name(item.path, analysis.root),
                "size": item.size,
                "human_size": human_size(item.size),
                "risk": item.risk,
                "category": item.category,
                "reason": item.reason,
                "action": item.action,
            }
            for item in analysis.insights[:40]
        ],
    }


def run_ai(args: argparse.Namespace) -> int:
    root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
    analysis = run_with_progress(
        f"Scai 正在扫描 {root}",
        lambda: create_space_analysis(root=root, limit=args.limit, include_all=args.all, max_depth=1),
    )
    payload = analysis_payload(analysis)

    codex = shutil.which("codex")
    if not codex:
        print("未找到 codex CLI。先输出本地规则分析摘要:")
        print()
        return run_brief(args)

    prompt = (
        "你是 Scai 的磁盘空间顾问。只根据下面 JSON 扫描摘要分析，不读取文件内容，"
        "不要建议直接永久删除。请用中文输出：空间概览、主要占用、可安全关注、需要确认、不要碰、下一步建议。"
        "可以使用 Markdown 标题、加粗、列表和代码块，不要使用 Markdown 表格。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    with tempfile.NamedTemporaryFile("r+", encoding="utf-8", delete=False) as output_file:
        output_path = output_file.name

    try:
        completed = subprocess.run(
            [
                codex,
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--output-last-message",
                output_path,
                "-",
            ],
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("Codex AI 分析超时，下面是本地规则分析摘要。", file=sys.stderr)
        print()
        return run_brief(args)
    else:
        if completed.returncode != 0:
            print("Codex AI 分析失败，下面是本地规则分析摘要。", file=sys.stderr)
            if completed.stderr.strip():
                print(completed.stderr.strip(), file=sys.stderr)
            print()
            return run_brief(args)
        with open(output_path, encoding="utf-8") as handle:
            message = handle.read().strip()
        message = message or completed.stdout.strip() or "Codex 没有返回分析内容。"
        print(render_markdown_for_terminal(message))
        return 0
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass


@dataclass
class TuiScanResult:
    mode: str
    root: Path
    records: list[FileRecord | DirectoryRecord]
    stats: ScanStats | None
    elapsed: float
    error: str | None = None


class ScaiTui:
    def __init__(self, args: argparse.Namespace) -> None:
        self.mode = args.mode
        self.root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
        self.limit = args.limit
        self.include_all = args.all
        self.max_depth = getattr(args, "max_depth", None)
        self.result: TuiScanResult | None = None
        self.scan_thread: threading.Thread | None = None
        self.scan_started_at = 0.0
        self.scroll = 0
        self.selected = 0
        self.message = ""
        self.show_help = False
        self.lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self.scan_thread is not None and self.scan_thread.is_alive()

    def start_scan(self) -> None:
        if self.busy:
            self.message = "扫描仍在进行中"
            return

        if self.mode == "dirs" and not self.root.is_dir():
            self.mode = "files"
            self.message = "文件路径不能使用目录模式，已切换到文件模式"

        root = self.root
        mode = self.mode
        limit = self.limit
        include_all = self.include_all
        max_depth = self.max_depth
        self.scan_started_at = time.time()
        self.scroll = 0
        self.selected = 0
        self.message = ""

        def worker() -> None:
            start = time.time()
            try:
                if mode == "dirs":
                    records, stats = scan_top_dirs(
                        root=root,
                        limit=limit,
                        include_all=include_all,
                        max_depth=max_depth,
                    )
                else:
                    records, stats = scan_top_files(root=root, limit=limit, include_all=include_all)
                result = TuiScanResult(
                    mode=mode,
                    root=root,
                    records=records,
                    stats=stats,
                    elapsed=time.time() - start,
                )
            except OSError as exc:
                result = TuiScanResult(mode=mode, root=root, records=[], stats=None, elapsed=time.time() - start, error=str(exc))

            with self.lock:
                self.result = result

        self.result = None
        self.scan_thread = threading.Thread(target=worker, daemon=True)
        self.scan_thread.start()

    def run(self, stdscr: curses.window) -> int:
        locale.setlocale(locale.LC_ALL, "")
        self.set_cursor(0)
        stdscr.keypad(True)
        stdscr.timeout(100)
        self.init_colors()
        self.start_scan()

        while True:
            self.draw(stdscr)
            key = stdscr.getch()
            if key == -1:
                continue
            if self.handle_key(stdscr, key):
                return 0

    def init_colors(self) -> None:
        if not curses.has_colors():
            return
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(2, curses.COLOR_CYAN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_GREEN, -1)
            curses.init_pair(5, curses.COLOR_RED, -1)
        except curses.error:
            pass

    def set_cursor(self, visibility: int) -> None:
        try:
            curses.curs_set(visibility)
        except curses.error:
            pass

    def color(self, pair: int) -> int:
        if not curses.has_colors():
            return 0
        return curses.color_pair(pair)

    def handle_key(self, stdscr: curses.window, key: int) -> bool:
        if key in (ord("q"), ord("Q"), 27):
            return True

        if key in (ord("?"),):
            self.show_help = not self.show_help
            return False

        if key in (curses.KEY_UP, ord("k"), ord("K")):
            self.move_selection(-1)
            return False
        if key in (curses.KEY_DOWN, ord("j"), ord("J")):
            self.move_selection(1)
            return False
        if key == curses.KEY_PPAGE:
            self.move_selection(-10)
            return False
        if key == curses.KEY_NPAGE:
            self.move_selection(10)
            return False

        if key in (ord("r"), ord("R")):
            self.start_scan()
            return False
        if key in (ord("f"), ord("F")):
            self.mode = "files"
            self.start_scan()
            return False
        if key in (ord("d"), ord("D")):
            self.mode = "dirs"
            self.start_scan()
            return False
        if key in (ord("c"), ord("C")):
            self.root = COMPUTER_SCAN_ROOT
            self.start_scan()
            return False
        if key in (ord("h"), ord("H")):
            self.root = DEFAULT_SCAN_ROOT
            self.start_scan()
            return False
        if key == ord("."):
            self.root = Path.cwd().resolve()
            self.start_scan()
            return False
        if key in (ord("a"), ord("A")):
            self.include_all = not self.include_all
            self.start_scan()
            return False
        if key in (ord("+"), ord("=")):
            self.limit = min(500, self.limit + 10)
            self.start_scan()
            return False
        if key in (ord("-"), ord("_")):
            self.limit = max(5, self.limit - 10)
            self.start_scan()
            return False
        if key == ord("]"):
            self.max_depth = 1 if self.max_depth is None else min(20, self.max_depth + 1)
            if self.mode == "dirs":
                self.start_scan()
            else:
                self.message = "max-depth 只对目录模式生效"
            return False
        if key == ord("["):
            if self.max_depth is None:
                self.message = "max-depth 当前未设置"
            elif self.max_depth <= 1:
                self.max_depth = None
                self.message = "已清除 max-depth"
                if self.mode == "dirs":
                    self.start_scan()
            else:
                self.max_depth -= 1
                if self.mode == "dirs":
                    self.start_scan()
            return False
        if key == ord("/"):
            self.prompt_path(stdscr)
            return False

        return False

    def move_selection(self, delta: int) -> None:
        result = self.result
        if not result or not result.records:
            return
        self.selected = max(0, min(len(result.records) - 1, self.selected + delta))
        height = shutil.get_terminal_size((120, 24)).lines
        visible_rows = max(1, height - 8)
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + visible_rows:
            self.scroll = self.selected - visible_rows + 1

    def prompt_path(self, stdscr: curses.window) -> None:
        height, width = stdscr.getmaxyx()
        prompt = "输入扫描路径: "
        self.safe_addstr(stdscr, height - 1, 0, " " * max(0, width - 1), curses.A_REVERSE)
        self.safe_addstr(stdscr, height - 1, 0, prompt, curses.A_REVERSE)
        curses.echo()
        self.set_cursor(1)
        stdscr.timeout(-1)
        try:
            raw = stdscr.getstr(height - 1, len(prompt), max(1, width - len(prompt) - 1)).decode().strip()
        except (UnicodeDecodeError, curses.error):
            raw = ""
        finally:
            curses.noecho()
            self.set_cursor(0)
            stdscr.timeout(100)

        if not raw:
            self.message = "路径未改变"
            return

        path = Path(raw).expanduser().resolve()
        if not path.exists():
            self.message = f"路径不存在: {path}"
            return

        self.root = path
        self.start_scan()

    def draw(self, stdscr: curses.window) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 10 or width < 60:
            self.safe_addstr(stdscr, 0, 0, "窗口太小，请放大终端。", self.color(5))
            stdscr.refresh()
            return

        self.draw_header(stdscr, width)
        self.draw_body(stdscr, height, width)
        self.draw_footer(stdscr, height, width)
        stdscr.refresh()

    def draw_header(self, stdscr: curses.window, width: int) -> None:
        mode_name = "文件" if self.mode == "files" else "文件夹"
        all_name = "全量" if self.include_all else "默认排除"
        depth = "-" if self.max_depth is None else str(self.max_depth)
        title = f" scai | {mode_name} | Top {self.limit} | {all_name} | depth {depth} "
        self.safe_addstr(stdscr, 0, 0, title.ljust(width - 1), self.color(1) or curses.A_REVERSE)
        root_text = f"路径: {self.root}"
        self.safe_addstr(stdscr, 1, 0, truncate_middle(root_text, width - 1), self.color(2))
        keys = "q退出  r刷新  f文件  d目录  /路径  c全盘  h用户目录  +/-数量  a排除开关  ?帮助"
        self.safe_addstr(stdscr, 2, 0, truncate_middle(keys, width - 1))

    def draw_body(self, stdscr: curses.window, height: int, width: int) -> None:
        if self.busy:
            elapsed = time.time() - self.scan_started_at
            frames = "|/-\\"
            frame = frames[int(elapsed * 8) % len(frames)]
            self.safe_addstr(stdscr, 4, 0, f"{frame} 扫描中... 已用时 {elapsed:.1f}s", self.color(3))
            self.safe_addstr(stdscr, 6, 0, "大目录可能需要一些时间，可以按 q 退出。")
            return

        result = self.result
        if not result:
            self.safe_addstr(stdscr, 4, 0, "暂无扫描结果，按 r 开始扫描。")
            return
        if result.error:
            self.safe_addstr(stdscr, 4, 0, f"扫描失败: {result.error}", self.color(5))
            return

        stats = result.stats or ScanStats()
        summary = (
            f"目录 {stats.scanned_dirs} 个 | 文件 {stats.scanned_files} 个 | "
            f"跳过目录 {stats.skipped_dirs} 个 | 其他跳过 {stats.skipped_entries} 个 | "
            f"用时 {result.elapsed:.2f}s"
        )
        self.safe_addstr(stdscr, 4, 0, truncate_middle(summary, width - 1), self.color(4))

        if not result.records:
            self.safe_addstr(stdscr, 6, 0, "没有找到可展示的记录。")
            return

        if result.mode == "dirs":
            self.draw_dir_rows(stdscr, result, height, width)
        else:
            self.draw_file_rows(stdscr, result, height, width)

        if self.show_help:
            self.draw_help(stdscr, height, width)

    def draw_file_rows(self, stdscr: curses.window, result: TuiScanResult, height: int, width: int) -> None:
        self.safe_addstr(stdscr, 6, 0, f"{'#':>3}  {'大小':>10}  {'格式':<8}  {'最近修改':<16}  文件")
        self.safe_addstr(stdscr, 7, 0, "-" * (width - 1))
        visible = max(1, height - 10)
        path_width = max(20, width - 45)

        for row, record in enumerate(result.records[self.scroll : self.scroll + visible], start=0):
            index = self.scroll + row
            assert isinstance(record, FileRecord)
            attr = curses.A_REVERSE if index == self.selected else 0
            name = truncate_middle(display_name(record.path, result.root), path_width)
            line = f"{index + 1:>3}  {human_size(record.size):>10}  {truncate_middle(infer_format(record.path), 8):<8}  {format_mtime(record.mtime)[:16]:<16}  {name}"
            self.safe_addstr(stdscr, 8 + row, 0, truncate_middle(line, width - 1), attr)

    def draw_dir_rows(self, stdscr: curses.window, result: TuiScanResult, height: int, width: int) -> None:
        self.safe_addstr(stdscr, 6, 0, f"{'#':>3}  {'总大小':>10}  {'文件数':>7}  {'最近修改':<16}  文件夹")
        self.safe_addstr(stdscr, 7, 0, "-" * (width - 1))
        visible = max(1, height - 10)
        path_width = max(20, width - 45)

        for row, record in enumerate(result.records[self.scroll : self.scroll + visible], start=0):
            index = self.scroll + row
            assert isinstance(record, DirectoryRecord)
            attr = curses.A_REVERSE if index == self.selected else 0
            name = truncate_middle(display_name(record.path, result.root), path_width)
            line = f"{index + 1:>3}  {human_size(record.size):>10}  {record.file_count:>7}  {format_mtime(record.mtime)[:16]:<16}  {name}"
            self.safe_addstr(stdscr, 8 + row, 0, truncate_middle(line, width - 1), attr)

    def draw_help(self, stdscr: curses.window, height: int, width: int) -> None:
        lines = [
            "帮助",
            "j/k 或 ↑/↓ 滚动，PageUp/PageDown 快速滚动",
            "f 文件模式，d 文件夹模式，r 重新扫描",
            "/ 输入路径，c 扫描电脑根目录，h 回到启动目录，. 当前目录",
            "+/- 调整 Top 数量，a 切换默认排除，[/] 调整目录深度",
            "q 退出，? 关闭帮助",
        ]
        box_width = min(width - 4, 78)
        start_y = max(3, (height - len(lines) - 2) // 2)
        start_x = max(2, (width - box_width) // 2)
        for offset, line in enumerate(lines):
            attr = self.color(1) if offset == 0 else curses.A_REVERSE
            self.safe_addstr(stdscr, start_y + offset, start_x, f" {truncate_middle(line, box_width - 2):<{box_width - 2}} ", attr or curses.A_REVERSE)

    def draw_footer(self, stdscr: curses.window, height: int, width: int) -> None:
        result = self.result
        position = ""
        if result and result.records:
            position = f" {self.selected + 1}/{len(result.records)}"
        text = f"{self.message}{position}"
        self.safe_addstr(stdscr, height - 1, 0, truncate_middle(text, width - 1).ljust(width - 1), curses.A_REVERSE)

    def safe_addstr(self, stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = stdscr.getmaxyx()
        if y < 0 or y >= height or x < 0 or x >= width:
            return
        max_len = max(0, width - x - 1)
        try:
            stdscr.addstr(y, x, text[:max_len], attr)
        except curses.error:
            pass


def add_common_args(parser: argparse.ArgumentParser, help_text: str, default_limit: int = DEFAULT_LIMIT) -> None:
    parser.add_argument(
        "root",
        nargs="?",
        default=str(DEFAULT_SCAN_ROOT),
        help=help_text,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help=f"输出前 N 条记录，默认 {default_limit}。",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="不跳过默认排除目录。注意：scai all 表示从 / 开始安全扫描，不等于 --all。",
    )
    parser.add_argument(
        "--computer",
        action="store_true",
        help="从电脑根目录 / 开始安全扫描；默认仍会跳过系统和缓存目录。",
    )


def add_dirs_args(parser: argparse.ArgumentParser) -> None:
    add_common_args(parser, "扫描根目录，默认是当前目录。")
    parser.add_argument(
        "--max-depth",
        type=int,
        help="只展示不超过指定层级的文件夹，例如 1 表示只看根目录下一层。",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=os.environ.get("SCAI_PROG", "scai"),
        description="Scai (Scan + AI) - CLI 为主、TUI 为辅的磁盘空间扫描与清理顾问。",
        epilog=(
            "核心用法:\n"
            "  scai                 输出 Space Brief 智能概览\n"
            "  scai all             从电脑根目录 / 开始安全扫描\n"
            "  scai top             查看最大文件\n"
            "  scai more            显示更多 Top 文件\n"
            "  scai dirs            查看最大文件夹\n"
            "  scai tui             打开 TUI 浏览\n"
            "  scai explain PATH    解释某个文件或目录\n"
            "  scai plan 20g        生成释放空间方案\n"
            "  scai ai              调用 Codex CLI 生成 AI 诊断\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    brief_parser = subparsers.add_parser("brief", help="输出默认 Space Brief 智能概览。")
    add_common_args(brief_parser, "扫描根目录，默认是当前目录。", default_limit=DEFAULT_BRIEF_LIMIT)

    top_parser = subparsers.add_parser("top", help="按文件大小输出 Top N。")
    add_common_args(top_parser, "扫描根目录，默认是当前目录。")

    more_parser = subparsers.add_parser("more", help=f"显示更多最大文件，默认 Top {DEFAULT_MORE_LIMIT}。")
    add_common_args(more_parser, "扫描根目录，默认是当前目录。", default_limit=DEFAULT_MORE_LIMIT)

    dirs_parser = subparsers.add_parser("dirs", help="按目录聚合后的总大小输出 Top N 文件夹。")
    add_dirs_args(dirs_parser)

    tui_parser = subparsers.add_parser("tui", help="打开 TUI 浏览文件或文件夹。")
    add_common_args(tui_parser, "扫描根目录，默认是当前目录。")
    tui_parser.add_argument("--mode", choices=("files", "dirs"), default="files", help="TUI 初始模式，默认 files。")
    tui_parser.add_argument("--max-depth", type=int, help="目录模式只展示不超过指定层级的文件夹。")

    explain_parser = subparsers.add_parser("explain", help="解释某个文件或目录的风险和建议。")
    explain_parser.add_argument("path", help="要解释的文件或目录路径。")
    explain_parser.add_argument("--all", action="store_true", help="解释目录时不跳过默认排除目录。")

    plan_parser = subparsers.add_parser("plan", help="生成释放指定空间的清理方案，不执行删除。")
    plan_parser.add_argument("target", help="目标释放空间，例如 10g、500m。")
    add_common_args(plan_parser, "扫描根目录，默认是当前目录。", default_limit=DEFAULT_ANALYSIS_LIMIT)

    ai_parser = subparsers.add_parser("ai", help="用 Codex CLI 对扫描摘要做 AI 诊断。")
    add_common_args(ai_parser, "扫描根目录，默认是当前目录。", default_limit=DEFAULT_BRIEF_LIMIT)
    ai_parser.add_argument("--timeout", type=int, default=180, help="Codex 分析超时时间，默认 180 秒。")

    return parser


def split_interface_args(raw_args: list[str]) -> tuple[list[str], bool, bool]:
    filtered: list[str] = []
    force_tui = False
    force_plain = False

    for arg in raw_args:
        lowered = arg.lower()
        if lowered in {"--tui", *TUI_ALIASES}:
            force_tui = True
            continue
        if lowered in {"--plain", *PLAIN_ALIASES}:
            force_plain = True
            continue
        filtered.append(arg)

    return filtered, force_tui, force_plain


def normalize_args(raw_args: list[str], program_name: str, force_tui: bool, force_plain: bool) -> list[str]:
    if len(raw_args) == 1 and raw_args[0].lower() in {"-h", "--help", "help", "h"}:
        return ["--help"]

    if force_tui:
        return normalize_command_args("tui", raw_args)

    if not raw_args:
        if program_name == "scan" or force_plain:
            return ["top"]
        return ["brief"]

    first = raw_args[0].lower()
    if force_plain and first not in COMMAND_ALIASES:
        return normalize_command_args("top", raw_args)

    if first in COMMAND_ALIASES:
        command = COMMAND_ALIASES[first]
        return normalize_command_args(command, raw_args[1:])

    if program_name == "scan":
        return normalize_command_args("top", raw_args)

    return normalize_command_args("brief", raw_args)


def normalize_command_args(command: str, raw_args: list[str]) -> list[str]:
    normalized: list[str] = []
    previous_option_needs_value = False

    for arg in raw_args:
        lowered = arg.lower()

        if previous_option_needs_value:
            normalized.append(arg)
            previous_option_needs_value = False
            continue

        if lowered in {"-h", "--help", "help", "h"}:
            normalized.append("--help")
            continue

        if arg in OPTIONS_REQUIRING_VALUE:
            normalized.append(arg)
            previous_option_needs_value = True
            continue

        if command == "tui" and lowered in {"f", "file", "files"}:
            normalized.extend(["--mode", "files"])
            continue

        if command == "tui" and lowered in {"d", "dir", "dirs"}:
            normalized.extend(["--mode", "dirs"])
            continue

        if lowered in COMPUTER_ROOT_ALIASES:
            normalized.append(str(COMPUTER_SCAN_ROOT))
            continue

        if arg.isdecimal():
            normalized.extend(["--limit", arg])
            continue

        normalized.append(arg)

    return [command, *normalized]


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if hasattr(args, "limit") and args.limit <= 0:
        parser.error("--limit 必须大于 0")
    if getattr(args, "max_depth", None) is not None and args.max_depth <= 0:
        parser.error("--max-depth 必须大于 0")

    if hasattr(args, "root"):
        root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
        if not root.exists():
            parser.error(f"路径不存在: {root}")

    if getattr(args, "command", "") == "dirs" and not root.is_dir():
        parser.error("dirs 模式需要传入目录路径")

    if getattr(args, "command", "") == "tui" and args.mode == "dirs" and not root.is_dir():
        parser.error("TUI 目录模式需要传入目录路径")

    if getattr(args, "command", "") == "explain":
        path = Path(args.path).expanduser().resolve()
        if not path.exists():
            parser.error(f"路径不存在: {path}")


def run_top(args: argparse.Namespace) -> int:
    root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
    start = time.time()
    records, stats = run_with_progress(
        f"Scai 正在扫描 {root}",
        lambda: scan_top_files(root=root, limit=args.limit, include_all=args.all),
    )
    elapsed = time.time() - start
    print_file_results(root=root, records=records, stats=stats, elapsed=elapsed, include_all=args.all)
    return 0


def run_more(args: argparse.Namespace) -> int:
    return run_top(args)


def run_dirs(args: argparse.Namespace) -> int:
    root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
    start = time.time()
    records, stats = run_with_progress(
        f"Scai 正在扫描 {root}",
        lambda: scan_top_dirs(
            root=root,
            limit=args.limit,
            include_all=args.all,
            max_depth=args.max_depth,
        ),
    )
    print_directory_results(root=root, records=records, stats=stats, elapsed=time.time() - start, include_all=args.all)
    return 0


def run_tui(args: argparse.Namespace) -> int:
    locale.setlocale(locale.LC_ALL, "")
    app = ScaiTui(args)
    return curses.wrapper(app.run)


def should_use_tui(program_name: str, force_tui: bool, force_plain: bool) -> bool:
    if force_plain:
        return False
    if force_tui:
        return True
    return False


def main() -> int:
    program_name = os.environ.get("SCAI_PROG", "scai")
    parser = build_parser()
    raw_args, force_tui, force_plain = split_interface_args(sys.argv[1:])
    normalized_args = normalize_args(raw_args, program_name=program_name, force_tui=force_tui, force_plain=force_plain)
    args = parser.parse_args(normalized_args)
    validate_args(parser, args)

    if args.command == "tui" or should_use_tui(program_name, force_tui, force_plain):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            if force_tui:
                print("TUI 需要交互式终端；请在真实终端运行 scai，或加 --plain 使用表格输出。", file=sys.stderr)
                return 2
            if args.command == "tui" and args.mode == "dirs":
                return run_dirs(args)
            return run_top(args)
        return run_tui(args)

    if args.command == "brief":
        return run_brief(args)
    if args.command == "top":
        return run_top(args)
    if args.command == "more":
        return run_more(args)
    if args.command == "dirs":
        return run_dirs(args)
    if args.command == "explain":
        return run_explain(args)
    if args.command == "plan":
        return run_plan(args)
    if args.command == "ai":
        return run_ai(args)

    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
