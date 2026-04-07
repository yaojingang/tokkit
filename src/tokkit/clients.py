from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APPLICATIONS_DIR = Path("/Applications")


@dataclass(frozen=True, slots=True)
class ClientDefinition:
    key: str
    label: str
    app_names: tuple[str, ...]
    default_coverage: str
    notes: str
    home_globs: tuple[str, ...] = ()

    @property
    def app_paths(self) -> tuple[Path, ...]:
        return tuple(APPLICATIONS_DIR / name for name in self.app_names)

    @property
    def probe_paths(self) -> tuple[Path, ...]:
        extra_paths: list[Path] = []
        home = Path.home()
        for pattern in self.home_globs:
            extra_paths.extend(home.glob(pattern))
        return (*self.app_paths, *extra_paths)


CLIENT_DEFINITIONS: tuple[ClientDefinition, ...] = (
    ClientDefinition(
        key="chatgpt",
        label="ChatGPT",
        app_names=("ChatGPT.app", "ChatGPT Atlas.app"),
        default_coverage="unavailable",
        notes="No local token ledger found yet.",
    ),
    ClientDefinition(
        key="warp",
        label="Warp",
        app_names=("Warp.app",),
        default_coverage="partial",
        notes="Local SQLite exposes aggregate usage and credits, not full input/output splits.",
    ),
    ClientDefinition(
        key="kaku",
        label="Kaku",
        app_names=("Kaku.app",),
        default_coverage="exact",
        notes="Exact only when traffic flows through the local TokKit proxy.",
    ),
    ClientDefinition(
        key="visual-studio-code",
        label="Visual Studio Code",
        app_names=("Visual Studio Code.app",),
        default_coverage="exact",
        notes="VS Code hosts multiple AI extensions. Codex is tracked today; Claude Code can be tracked from local Claude sessions.",
    ),
    ClientDefinition(
        key="claude-code",
        label="Claude Code",
        app_names=(),
        default_coverage="exact",
        notes="Exact when local Claude session JSONL and matching debug logs are available.",
        home_globs=(".vscode/extensions/anthropic.claude-code-*",),
    ),
    ClientDefinition(
        key="augment",
        label="Augment",
        app_names=(),
        default_coverage="unavailable",
        notes=(
            "Historical local logs still do not expose a stable token ledger. "
            "TokKit can capture exact usage from new Augment requests by patching the VS Code extension "
            "at runtime, then scanning `~/.tokkit/augment-usage.ndjson`."
        ),
        home_globs=(".vscode/extensions/augment.vscode-augment-*",),
    ),
    ClientDefinition(
        key="codex",
        label="Codex",
        app_names=("Codex.app",),
        default_coverage="exact",
        notes="Codex CLI and desktop session logs provide precise token counts.",
    ),
    ClientDefinition(
        key="cursor",
        label="Cursor",
        app_names=("Cursor.app",),
        default_coverage="unavailable",
        notes=(
            "Experimental estimated coverage is available from local sentry `ex_hs2` events. "
            "No exact billable token ledger has been found locally."
        ),
    ),
    ClientDefinition(
        key="trae",
        label="Trae",
        app_names=("Trae.app",),
        default_coverage="unavailable",
        notes="Local logs show app activity, not token usage totals.",
    ),
    ClientDefinition(
        key="codebuddy",
        label="CodeBuddy",
        app_names=("CodeBuddy.app",),
        default_coverage="estimated",
        notes="Estimated from local conversation history snapshots, not official usage.",
    ),
)


CLIENTS_BY_KEY = {client.key: client for client in CLIENT_DEFINITIONS}


def detect_installed_clients() -> dict[str, bool]:
    return {
        client.key: any(path.exists() for path in client.probe_paths)
        for client in CLIENT_DEFINITIONS
    }


def logical_client_for_usage_row(app: str, source: str) -> str | None:
    if app == "codex" and source == "codex:vscode":
        return "visual-studio-code"
    if app == "codex":
        return "codex"
    if app == "augment":
        return "augment"
    if app == "claude-code":
        return "claude-code"
    if app == "warp":
        return "warp"
    if app == "kaku":
        return "kaku"
    if app == "codebuddy":
        return "codebuddy"
    if app == "cursor":
        return "cursor"
    return None
