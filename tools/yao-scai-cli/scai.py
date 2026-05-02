#!/usr/bin/env python3
from __future__ import annotations

import argparse
import curses
import heapq
import locale
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_SCAN_ROOT = Path.home()
DEFAULT_LIMIT = 20
COMPUTER_SCAN_ROOT = Path("/")
COMPRESSED_SUFFIXES = {".gz", ".bz2", ".xz", ".zip", ".zst"}
MODE_ALIASES = {
    "f": "files",
    "file": "files",
    "files": "files",
    "d": "dirs",
    "dir": "dirs",
    "dirs": "dirs",
}
COMPUTER_ROOT_ALIASES = {"c", "computer", "mac", "root", "全盘", "电脑", "根目录"}
OPTIONS_REQUIRING_VALUE = {"--limit", "--max-depth"}
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
    if any(path_str == prefix or path_str.startswith(prefix + os.sep) for prefix in SYSTEM_ROOT_PREFIXES):
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
            "/ 输入路径，c 扫描电脑根目录，h 回到用户目录，. 当前目录",
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


def add_common_args(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "root",
        nargs="?",
        default=str(DEFAULT_SCAN_ROOT),
        help=help_text,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"输出前 N 条记录，默认 {DEFAULT_LIMIT}。",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="不跳过默认排除目录，做全量扫描。",
    )
    parser.add_argument(
        "--computer",
        action="store_true",
        help="从电脑根目录 / 开始扫描；默认仍会跳过系统和缓存目录。",
    )


def add_dirs_args(parser: argparse.ArgumentParser) -> None:
    add_common_args(parser, "扫描根目录，默认是当前用户主目录。")
    parser.add_argument(
        "--max-depth",
        type=int,
        help="只展示不超过指定层级的文件夹，例如 1 表示只看根目录下一层。",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=os.environ.get("SCAI_PROG", "scai"),
        description="Scai (Scan + AI) - AI 原生的磁盘空间扫描与清理顾问，默认打开 TUI 界面。",
        epilog=(
            "极简用法:\n"
            "  scai                打开 TUI 查看当前用户目录\n"
            "  scai 50             打开 TUI，查看前 50 条\n"
            "  scai d              打开 TUI，默认进入文件夹模式\n"
            "  scai c              打开 TUI，从电脑根目录开始安全扫描\n"
            "  scai ~/Downloads    打开 TUI，只扫描下载目录\n"
            "  scai --plain        使用表格输出\n"
            "  bf                  旧别名，兼容入口\n"
            "  scan                兼容入口，默认使用表格输出\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="mode")

    files_parser = subparsers.add_parser("files", help="按文件大小输出 Top N。")
    add_common_args(files_parser, "扫描根目录，默认是当前用户主目录。")

    dirs_parser = subparsers.add_parser("dirs", help="按目录聚合后的总大小输出 Top N 文件夹。")
    add_dirs_args(dirs_parser)

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


def normalize_args(raw_args: list[str]) -> list[str]:
    if len(raw_args) == 1 and raw_args[0].lower() in {"-h", "--help", "help", "h"}:
        return ["--help"]

    mode = "files"
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

        if lowered in MODE_ALIASES:
            mode = MODE_ALIASES[lowered]
            continue

        if lowered in COMPUTER_ROOT_ALIASES:
            normalized.append(str(COMPUTER_SCAN_ROOT))
            continue

        if arg.isdecimal():
            normalized.extend(["--limit", arg])
            continue

        if lowered == "all":
            normalized.append("--all")
            continue

        normalized.append(arg)

    return [mode, *normalized]


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.limit <= 0:
        parser.error("--limit 必须大于 0")
    if getattr(args, "max_depth", None) is not None and args.max_depth <= 0:
        parser.error("--max-depth 必须大于 0")

    root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
    if not root.exists():
        parser.error(f"路径不存在: {root}")

    if args.mode == "dirs" and not root.is_dir():
        parser.error("dirs 模式需要传入目录路径")


def run_plain(args: argparse.Namespace) -> int:
    root = COMPUTER_SCAN_ROOT if args.computer else Path(args.root).expanduser().resolve()
    start = time.time()
    if args.mode == "dirs":
        records, stats = scan_top_dirs(
            root=root,
            limit=args.limit,
            include_all=args.all,
            max_depth=args.max_depth,
        )
        print_directory_results(root=root, records=records, stats=stats, elapsed=time.time() - start, include_all=args.all)
        return 0

    records, stats = scan_top_files(root=root, limit=args.limit, include_all=args.all)
    elapsed = time.time() - start
    print_file_results(root=root, records=records, stats=stats, elapsed=elapsed, include_all=args.all)
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
    return program_name in {"scai", "bf"}


def main() -> int:
    parser = build_parser()
    raw_args, force_tui, force_plain = split_interface_args(sys.argv[1:])
    args = parser.parse_args(normalize_args(raw_args))
    validate_args(parser, args)

    program_name = os.environ.get("SCAI_PROG", "scai")
    use_tui = should_use_tui(program_name, force_tui, force_plain)
    if use_tui:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            if force_tui:
                print("TUI 需要交互式终端；请在真实终端运行 scai，或加 --plain 使用表格输出。", file=sys.stderr)
                return 2
            return run_plain(args)
        return run_tui(args)

    return run_plain(args)


if __name__ == "__main__":
    sys.exit(main())
