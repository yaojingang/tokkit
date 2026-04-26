from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .utils import json_dumps, resolve_app_home


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


_STATE_FILE_NAME = "scan-sessions.json"
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
_MAX_SESSION_AGE = timedelta(days=14)
_MAX_SESSION_COUNT = 48


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
    state = load_scan_sessions_state(app_home=app_home)
    session = state.get("sessions", {}).get(effective_session_key, {})
    active_targets = tuple(_normalize_targets(session.get("active_targets", [])))
    full_scan_completed = bool(session.get("full_scan_completed"))

    if force_full or not full_scan_completed or not active_targets:
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


def record_scan_plan_result(
    plan: ScanPlan,
    *,
    active_targets: Iterable[str],
    scanned_targets: Iterable[str] | None = None,
    app_home: Path | None = None,
) -> None:
    state = load_scan_sessions_state(app_home=app_home)
    sessions = state.setdefault("sessions", {})
    previous = sessions.get(plan.session_key, {})
    now = datetime.now(timezone.utc).isoformat()
    sessions[plan.session_key] = {
        "active_targets": list(_normalize_targets(active_targets)),
        "full_scan_completed": bool(previous.get("full_scan_completed")) or plan.full_scan,
        "last_mode": "full" if plan.full_scan else "targeted",
        "last_scan_at": now,
        "last_scanned_targets": list(_normalize_targets(scanned_targets or plan.targets)),
    }
    _prune_sessions(sessions)
    save_scan_sessions_state(state, app_home=app_home)


def load_scan_sessions_state(*, app_home: Path | None = None) -> dict[str, Any]:
    path = scan_sessions_path(app_home=app_home)
    if not path.exists():
        return {"sessions": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"sessions": {}}
    if not isinstance(payload, dict):
        return {"sessions": {}}
    sessions = payload.get("sessions")
    if not isinstance(sessions, dict):
        return {"sessions": {}}
    normalized: dict[str, Any] = {}
    for key, value in sessions.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, dict):
            continue
        normalized[key] = value
    return {"sessions": normalized}


def save_scan_sessions_state(state: dict[str, Any], *, app_home: Path | None = None) -> None:
    path = scan_sessions_path(app_home=app_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(state), encoding="utf-8")


def scan_sessions_path(*, app_home: Path | None = None) -> Path:
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


def _prune_sessions(sessions: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    stale_keys: list[str] = []
    ranked: list[tuple[datetime, str]] = []
    for key, value in sessions.items():
        last_scan_at = _parse_timestamp(value.get("last_scan_at"))
        if last_scan_at is None or now - last_scan_at > _MAX_SESSION_AGE:
            stale_keys.append(key)
            continue
        ranked.append((last_scan_at, key))

    for key in stale_keys:
        sessions.pop(key, None)

    if len(ranked) <= _MAX_SESSION_COUNT:
        return

    ranked.sort(reverse=True)
    keep = {key for _, key in ranked[:_MAX_SESSION_COUNT]}
    for key in list(sessions):
        if key not in keep:
            sessions.pop(key, None)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
