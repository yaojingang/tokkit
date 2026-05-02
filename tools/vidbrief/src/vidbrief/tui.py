from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .downloader import DEFAULT_VIDEO_FORMAT
from .utils import is_url


@dataclass
class TuiResult:
    action: str
    url: str
    output: Path
    cookies_from_browser: str | None
    report_provider: str
    language: str
    video_format: str


ACTION_CHOICES = (
    ("run", "run - download + transcript + report"),
    ("info", "info - metadata only"),
    ("download", "download - media + subtitles only"),
)
BROWSER_CHOICES = (
    ("", "none"),
    ("chrome", "chrome"),
    ("safari", "safari"),
    ("firefox", "firefox"),
    ("edge", "edge"),
    ("brave", "brave"),
)
REPORT_PROVIDER_CHOICES = (
    ("auto", "auto"),
    ("codex", "codex"),
    ("openai", "openai"),
    ("none", "none"),
)
LANGUAGE_CHOICES = (
    ("zh-CN", "zh-CN"),
    ("en", "en"),
)
QUALITY_CHOICES = (
    (DEFAULT_VIDEO_FORMAT, "720p default"),
    ("best", "best available"),
)


class TuiCancelled(Exception):
    pass


class VideoBriefTui:
    def __init__(self, stdscr, *, default_output_dir: Path, default_report_provider: str) -> None:
        self.stdscr = stdscr
        self.url = ""
        self.output = str(default_output_dir)
        self.action_index = 0
        self.browser_index = 0
        self.report_provider_index = _choice_index(REPORT_PROVIDER_CHOICES, default_report_provider)
        self.language_index = 0
        self.quality_index = 0
        self.focus = 0
        self.status = "Paste a URL, choose options, then Start. Esc exits."
        self.fields = (
            "url",
            "action",
            "output",
            "browser",
            "provider",
            "language",
            "quality",
            "start",
        )

    def run(self) -> TuiResult:
        import curses

        curses.curs_set(0)
        self.stdscr.keypad(True)
        self._setup_colors(curses)

        while True:
            self._render(curses)
            key = self.stdscr.get_wch()
            result = self._handle_key(key, curses)
            if result is not None:
                return result

    def _setup_colors(self, curses) -> None:
        if not curses.has_colors():
            self.selected_attr = curses.A_REVERSE
            self.hint_attr = curses.A_DIM
            self.error_attr = curses.A_BOLD
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(2, curses.COLOR_BLACK, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_GREEN, -1)
        self.selected_attr = curses.color_pair(1)
        self.hint_attr = curses.color_pair(2) | curses.A_DIM
        self.error_attr = curses.color_pair(3) | curses.A_BOLD
        self.ok_attr = curses.color_pair(4) | curses.A_BOLD

    def _render(self, curses) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        if height < 18 or width < 64:
            _addn(self.stdscr, 0, 0, "Terminal too small. Resize to at least 64x18.", width - 1, curses.A_BOLD)
            self.stdscr.refresh()
            return

        _addn(self.stdscr, 0, 0, "vb TUI - Video Brief / 视频下载、解析、报告", width - 1, curses.A_BOLD)
        _addn(self.stdscr, 1, 0, "Up/Down move  Left/Right switch  Type/paste edit  Enter start  Esc exit", width - 1, self.hint_attr)

        rows = [
            ("URL", self.url or "<paste video URL>", "text"),
            ("Action", self._choice_label(ACTION_CHOICES, self.action_index), "choice"),
            ("Output", self.output, "text"),
            ("Browser cookies", self._choice_label(BROWSER_CHOICES, self.browser_index), "choice"),
            ("Report provider", self._choice_label(REPORT_PROVIDER_CHOICES, self.report_provider_index), "choice"),
            ("Language", self._choice_label(LANGUAGE_CHOICES, self.language_index), "choice"),
            ("Quality", self._choice_label(QUALITY_CHOICES, self.quality_index), "choice"),
            ("Start", "Run selected action", "button"),
        ]

        for index, (label, value, kind) in enumerate(rows):
            y = 3 + index * 2
            selected = index == self.focus
            attr = self.selected_attr if selected else curses.A_NORMAL
            marker = ">" if selected else " "
            _addn(self.stdscr, y, 0, f"{marker} {label:<16}", 20, attr)
            value_attr = attr if selected else (self.hint_attr if value.startswith("<") else curses.A_NORMAL)
            _addn(self.stdscr, y, 20, value, width - 22, value_attr)
            if kind == "choice":
                _addn(self.stdscr, y + 1, 22, "Use Left/Right to change.", width - 24, self.hint_attr)
            elif kind == "text" and selected:
                _addn(self.stdscr, y + 1, 22, "Type or paste. Backspace deletes. Ctrl-U clears.", width - 24, self.hint_attr)

        status_attr = self.error_attr if self.status.startswith("Error:") else self.hint_attr
        _addn(self.stdscr, height - 2, 0, self.status, width - 1, status_attr)
        self.stdscr.refresh()

    def _handle_key(self, key, curses) -> TuiResult | None:
        if isinstance(key, str) and key == "\x1b":
            raise TuiCancelled()
        if key in (curses.KEY_UP, "\x10"):
            self.focus = (self.focus - 1) % len(self.fields)
            return None
        if key in (curses.KEY_DOWN, "\x0e", "\t"):
            self.focus = (self.focus + 1) % len(self.fields)
            return None
        if key in (curses.KEY_LEFT,):
            self._cycle_choice(-1)
            return None
        if key in (curses.KEY_RIGHT,):
            self._cycle_choice(1)
            return None
        if key in (curses.KEY_ENTER, "\n", "\r"):
            if self.fields[self.focus] == "start":
                return self._submit()
            self.focus = (self.focus + 1) % len(self.fields)
            return None
        if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            self._backspace_text()
            return None
        if key == "\x15":
            self._clear_text()
            return None
        if isinstance(key, str) and key.isprintable():
            self._append_text(key)
        return None

    def _submit(self) -> TuiResult | None:
        url = self.url.strip()
        if not is_url(url):
            self.status = "Error: paste a valid http(s) video URL first."
            self.focus = 0
            return None

        output = Path(self.output.strip() or ".").expanduser()
        action = ACTION_CHOICES[self.action_index][0]
        cookies = BROWSER_CHOICES[self.browser_index][0] or None
        provider = REPORT_PROVIDER_CHOICES[self.report_provider_index][0]
        language = LANGUAGE_CHOICES[self.language_index][0]
        video_format = QUALITY_CHOICES[self.quality_index][0]
        return TuiResult(
            action=action,
            url=url,
            output=output,
            cookies_from_browser=cookies,
            report_provider=provider,
            language=language,
            video_format=video_format,
        )

    def _cycle_choice(self, delta: int) -> None:
        field = self.fields[self.focus]
        if field == "action":
            self.action_index = (self.action_index + delta) % len(ACTION_CHOICES)
        elif field == "browser":
            self.browser_index = (self.browser_index + delta) % len(BROWSER_CHOICES)
        elif field == "provider":
            self.report_provider_index = (self.report_provider_index + delta) % len(REPORT_PROVIDER_CHOICES)
        elif field == "language":
            self.language_index = (self.language_index + delta) % len(LANGUAGE_CHOICES)
        elif field == "quality":
            self.quality_index = (self.quality_index + delta) % len(QUALITY_CHOICES)

    def _append_text(self, value: str) -> None:
        field = self.fields[self.focus]
        if field == "url":
            self.url += value
        elif field == "output":
            self.output += value

    def _backspace_text(self) -> None:
        field = self.fields[self.focus]
        if field == "url":
            self.url = self.url[:-1]
        elif field == "output":
            self.output = self.output[:-1]

    def _clear_text(self) -> None:
        field = self.fields[self.focus]
        if field == "url":
            self.url = ""
        elif field == "output":
            self.output = ""

    @staticmethod
    def _choice_label(choices: tuple[tuple[str, str], ...], index: int) -> str:
        return choices[index][1]


def run_tui(*, default_output_dir: Path, default_report_provider: str) -> TuiResult | None:
    import curses

    try:
        return curses.wrapper(
            lambda stdscr: VideoBriefTui(
                stdscr,
                default_output_dir=default_output_dir,
                default_report_provider=default_report_provider,
            ).run()
        )
    except TuiCancelled:
        return None


def _choice_index(choices: tuple[tuple[str, str], ...], value: str) -> int:
    for index, (choice_value, _) in enumerate(choices):
        if choice_value == value:
            return index
    return 0


def _addn(stdscr, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    if width <= 0:
        return
    try:
        stdscr.addnstr(y, x, text, width, attr)
    except Exception:
        pass
