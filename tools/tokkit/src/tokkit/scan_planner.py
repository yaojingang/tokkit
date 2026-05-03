from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import sqlite3

from .utils import json_dumps, resolve_app_home, today_string


ALL_SCAN_TARGETS: tuple[str, ...] = (
    "codex",
    "claude-code",
    "augment",
    "chatgpt",
    "copilot",
    "codebuddy",
    "cursor",
    "trae",
    "warp",
)


SCAN_TARGET_LABELS: dict[str, str] = {
    "codex": "Codex",
    "claude-code": "Claude Code",
    "augment": "Augment",
    "chatgpt": "ChatGPT export",
    "copilot": "GitHub Copilot export",
    "codebuddy": "CodeBuddy",
    "cursor": "Cursor",
    "trae": "Trae",
    "warp": "Warp",
}


SCAN_TARGET_COMMANDS: dict[str, list[str]] = {
    "codex": ["scan-codex"],
    "claude-code": ["scan-claude-code"],
    "augment": ["scan-augment"],
    "chatgpt": ["scan-chatgpt-export"],
    "copilot": ["scan-copilot"],
    "codebuddy": ["scan-codebuddy"],
    "cursor": ["scan-cursor"],
    "trae": ["scan-trae"],
    "warp": ["scan-warp"],
}


ACTIVE_SCAN_LOOKBACK_DAYS = 30
_STATE_FILE_NAME = "scan-plan.json"
_TERMINAL_SESSION_ENV_KEYS = (
    "TERM_SESSION_ID",
    "ITERM_SESSION_ID",
    "KITTY_WINDOW_ID",
    "KITTY_PID",
    "TMUX_PANE",
    "WEZTERM_PANE",
    "WINDOWID",
    "STY",
    "ALACRITTY_WINDOW_ID",
)


@dataclass(frozen=True, slots=True)
class ScanPlan:
    session_key: str
    targets: tuple[str, ...]
    full_scan: bool
    label: str


def scan_command_for_target(target: str) -> list[str]:
    command = SCAN_TARGET_COMMANDS.get(target)
    if command is None:
        raise KeyError(target)
    return list(command)


def scan_targets_label(targets: Iterable[str]) -> str:
    labels = [
        SCAN_TARGET_LABELS.get(target, target.replace("-", " ").title())
        for target in _normalize_targets(targets)
    ]
    return " + ".join(labels)


def current_scan_session_key() -> str:
    explicit = os.environ.get("TOKKIT_SCAN_SESSION_KEY", "").strip()
    if explicit:
        return explicit

    components: list[str] = []
    for name in _TERMINAL_SESSION_ENV_KEYS:
        value = os.environ.get(name, "").strip()
        if value:
            components.append(f"{name.lower()}={value}")

    tty_value = _current_tty()
    if tty_value:
        components.append(f"tty={tty_value}")

    interactive = sys.stdin.isatty() or sys.stdout.isatty() or sys.stderr.isatty()
    if interactive:
        components.append(f"ppid={os.getppid()}")

    if not components:
        return "background"
    return "terminal:" + "|".join(components)


def resolve_scan_plan(
    *,
    force_full: bool = False,
    session_key: str | None = None,
    app_home: Path | None = None,
) -> ScanPlan:
    effective_session_key = session_key or current_scan_session_key()
    state = load_scan_plan_state(app_home=app_home)
    active_targets = tuple(_normalize_targets(state.get("active_targets", [])))
    bootstrap_completed = bool(state.get("bootstrap_completed"))

    if force_full or not bootstrap_completed or not active_targets:
        targets = ALL_SCAN_TARGETS
        full_scan = True
    else:
        targets = active_targets
        full_scan = False

    return ScanPlan(
        session_key=effective_session_key,
        targets=targets,
        full_scan=full_scan,
        label=scan_targets_label(targets),
    )


def recent_active_targets(
    conn: sqlite3.Connection,
    tz,
    *,
    lookback_days: int = ACTIVE_SCAN_LOOKBACK_DAYS,
) -> tuple[str, ...]:
    today = today_string(tz)
    rows = conn.execute(
        """
        SELECT DISTINCT app
        FROM usage_records
        WHERE local_date >= date(?, ?)
          AND (
              COALESCE(total_tokens, 0) > 0
              OR COALESCE(input_tokens, 0) > 0
              OR COALESCE(output_tokens, 0) > 0
              OR COALESCE(cached_input_tokens, 0) > 0
              OR COALESCE(reasoning_tokens, 0) > 0
              OR COALESCE(credits, 0.0) > 0.0
          )
        """,
        (today, f"-{max(lookback_days - 1, 0)} day"),
    ).fetchall()

    detected = {str(row["app"]).strip() for row in rows if str(row["app"]).strip()}
    return tuple(target for target in ALL_SCAN_TARGETS if target in detected)


def record_scan_plan_result(
    plan: ScanPlan,
    *,
    active_targets: Iterable[str],
    scanned_targets: Iterable[str] | None = None,
    app_home: Path | None = None,
    lookback_days: int = ACTIVE_SCAN_LOOKBACK_DAYS,
) -> None:
    previous = load_scan_plan_state(app_home=app_home)
    normalized_active_targets = list(_normalize_targets(active_targets))
    now = datetime.now(timezone.utc).isoformat()

    if plan.full_scan:
        persisted_targets = normalized_active_targets
    else:
        previous_targets = list(_normalize_targets(previous.get("active_targets", [])))
        persisted_targets = previous_targets or normalized_active_targets

    payload = {
        "bootstrap_completed": bool(previous.get("bootstrap_completed")) or plan.full_scan,
        "active_targets": persisted_targets,
        "lookback_days": int(previous.get("lookback_days") or lookback_days),
        "last_mode": "full" if plan.full_scan else "targeted",
        "last_scan_at": now,
        "last_session_key": plan.session_key,
        "last_scanned_targets": list(_normalize_targets(scanned_targets or plan.targets)),
    }
    save_scan_plan_state(payload, app_home=app_home)


def load_scan_plan_state(*, app_home: Path | None = None) -> dict[str, Any]:
    path = scan_plan_path(app_home=app_home)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def save_scan_plan_state(state: dict[str, Any], *, app_home: Path | None = None) -> None:
    path = scan_plan_path(app_home=app_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(state), encoding="utf-8")


def scan_plan_path(*, app_home: Path | None = None) -> Path:
    return (app_home or resolve_app_home()) / _STATE_FILE_NAME


def _normalize_targets(targets: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for target in targets:
        if not isinstance(target, str):
            continue
        key = target.strip()
        if key not in SCAN_TARGET_LABELS or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return tuple(normalized)


def _current_tty() -> str | None:
    for stream in (0, 1, 2):
        try:
            return os.ttyname(stream)
        except OSError:
            continue
    return None
