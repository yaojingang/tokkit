from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .utils import resolve_app_home


DEFAULT_BUDGET_PATH = resolve_app_home() / "budget.json"


@dataclass(frozen=True)
class BudgetConfig:
    currency: str = "USD"
    daily_est_usd: float | None = None
    weekly_est_usd: float | None = None
    monthly_est_usd: float | None = None
    daily_credits: float | None = None
    weekly_credits: float | None = None
    monthly_credits: float | None = None


@dataclass(frozen=True)
class BudgetResolution:
    path: Path
    exists: bool
    loaded: bool
    config: BudgetConfig
    error: str | None = None


def resolve_budget_config(path: Path | None = None) -> BudgetResolution:
    budget_path = Path(
        os.environ.get(
            "TOKKIT_BUDGET_PATH",
            os.environ.get("TOKSTAT_BUDGET_PATH", str(path or DEFAULT_BUDGET_PATH)),
        )
    ).expanduser()

    if not budget_path.exists():
        return BudgetResolution(
            path=budget_path,
            exists=False,
            loaded=False,
            config=BudgetConfig(),
        )

    try:
        payload = json.loads(budget_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("budget config must be a JSON object")
        config = BudgetConfig(
            currency=str(payload.get("currency") or "USD"),
            daily_est_usd=_read_optional_float(payload, "daily_est_usd"),
            weekly_est_usd=_read_optional_float(payload, "weekly_est_usd"),
            monthly_est_usd=_read_optional_float(payload, "monthly_est_usd"),
            daily_credits=_read_optional_float(payload, "daily_credits"),
            weekly_credits=_read_optional_float(payload, "weekly_credits"),
            monthly_credits=_read_optional_float(payload, "monthly_credits"),
        )
        return BudgetResolution(
            path=budget_path,
            exists=True,
            loaded=True,
            config=config,
        )
    except Exception as exc:
        return BudgetResolution(
            path=budget_path,
            exists=True,
            loaded=False,
            config=BudgetConfig(),
            error=str(exc),
        )


def write_budget_template(path: Path | None = None, *, force: bool = False) -> Path:
    resolution = resolve_budget_config(path)
    budget_path = resolution.path
    if budget_path.exists() and not force:
        raise FileExistsError(f"budget config already exists: {budget_path}")

    budget_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "currency": "USD",
        "daily_est_usd": 25.0,
        "weekly_est_usd": 150.0,
        "monthly_est_usd": 600.0,
        "daily_credits": None,
        "weekly_credits": None,
        "monthly_credits": None,
    }
    budget_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return budget_path


def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    return float(value)
