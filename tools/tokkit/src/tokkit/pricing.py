from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import resolve_app_home


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    cached_input_per_million: float | None
    output_per_million: float


@dataclass(frozen=True)
class PriceProfile:
    model: str
    pricing: ModelPrice
    source: str


@dataclass(frozen=True)
class PriceBookResolution:
    profiles: dict[str, PriceProfile]
    override_path: Path
    override_loaded: bool
    override_error: str | None = None


_PAREN_SUFFIX_RE = re.compile(r"\s*(\([^)]*\))\s*$")
_CLAUDE_PREFIX_RE = re.compile(r"^claude\s+(sonnet|opus|haiku)\s+([0-9.]+)(.*)$", re.IGNORECASE)
_CLAUDE_SUFFIX_RE = re.compile(r"^claude\s+([0-9.]+)\s+(sonnet|opus|haiku)(.*)$", re.IGNORECASE)
_CLAUDE_API_RE = re.compile(
    r"^claude[- ]?(sonnet|opus|haiku)[- ]?(\d+(?:[-.]\d+)?)(?:[- ]\d{8})?(.*)$",
    re.IGNORECASE,
)
_GPT_RE = re.compile(r"^gpt[- ]?([0-9.]+)(?:[- ]?(mini|nano|codex|pro))?(.*)$", re.IGNORECASE)
DEFAULT_PRICING_PATH = resolve_app_home() / "pricing.json"


BUILTIN_PRICE_BOOK: dict[str, ModelPrice] = {
    "GPT-5.5": ModelPrice(5.00, 0.50, 30.00),
    "GPT-5.5 Pro": ModelPrice(30.00, None, 180.00),
    "GPT-5.4": ModelPrice(2.50, 0.25, 15.00),
    "GPT-5.4 Pro": ModelPrice(30.00, None, 180.00),
    "GPT-5.4 Mini": ModelPrice(0.75, 0.075, 4.50),
    "GPT-5.4 Nano": ModelPrice(0.20, 0.02, 1.25),
    "GPT-5.3 Codex": ModelPrice(1.75, 0.175, 14.00),
    "GPT-5.2 Pro": ModelPrice(21.00, None, 168.00),
    "GPT-5.2": ModelPrice(1.75, 0.175, 14.00),
    "GPT-5.2 Codex": ModelPrice(1.75, 0.175, 14.00),
    "GPT-5 Pro": ModelPrice(15.00, None, 120.00),
    "GPT-5": ModelPrice(1.25, 0.125, 10.00),
    "GPT-5 Codex": ModelPrice(1.25, 0.125, 10.00),
    "GPT-5 Mini": ModelPrice(0.25, 0.025, 2.00),
    "GPT-5 Nano": ModelPrice(0.05, 0.005, 0.40),
    "GPT-4.1": ModelPrice(2.00, 0.50, 8.00),
    "GPT-4.1 Mini": ModelPrice(0.40, 0.10, 1.60),
    "GPT-4.1 Nano": ModelPrice(0.10, 0.025, 0.40),
    "Claude Sonnet 4.6": ModelPrice(3.00, 0.30, 15.00),
    "Claude Sonnet 4.5": ModelPrice(3.00, 0.30, 15.00),
    "Claude Haiku 4.5": ModelPrice(1.00, 0.10, 5.00),
    "Claude Opus 4.7": ModelPrice(5.00, 0.50, 25.00),
    "Claude Opus 4.6": ModelPrice(5.00, 0.50, 25.00),
    "Claude Opus 4.5": ModelPrice(5.00, 0.50, 25.00),
    "Claude Sonnet 4": ModelPrice(3.00, 0.30, 15.00),
    "Claude Opus 4": ModelPrice(15.00, 1.50, 75.00),
}


def resolve_price_book(pricing_path: Path | None = None) -> PriceBookResolution:
    override_path = Path(
        os.environ.get(
            "TOKKIT_PRICING_PATH",
            os.environ.get("TOKSTAT_PRICING_PATH", str(pricing_path or DEFAULT_PRICING_PATH)),
        )
    ).expanduser()
    profiles: dict[str, PriceProfile] = {
        model: PriceProfile(model=model, pricing=pricing, source="built-in")
        for model, pricing in BUILTIN_PRICE_BOOK.items()
    }

    if not override_path.exists():
        return PriceBookResolution(
            profiles=profiles,
            override_path=override_path,
            override_loaded=False,
        )

    try:
        for model, pricing in _load_override_profiles(override_path).items():
            profiles[model] = PriceProfile(model=model, pricing=pricing, source="override")
        return PriceBookResolution(
            profiles=profiles,
            override_path=override_path,
            override_loaded=True,
        )
    except Exception as exc:
        return PriceBookResolution(
            profiles=profiles,
            override_path=override_path,
            override_loaded=False,
            override_error=str(exc),
        )


def iter_price_book(resolution: PriceBookResolution | None = None) -> list[PriceProfile]:
    return list((resolution or resolve_price_book()).profiles.values())


def normalize_model_display(model: str | None, provider: str | None = None) -> str:
    model_value = (model or "").strip()
    provider_value = (provider or "").strip()
    if not model_value:
        if provider_value:
            return f"unknown (provider={provider_value})"
        return "unknown"

    suffix = ""
    suffix_match = _PAREN_SUFFIX_RE.search(model_value)
    if suffix_match:
        suffix = f" {suffix_match.group(1)}"
        model_value = model_value[: suffix_match.start()].strip()

    normalized = _normalize_claude(model_value)
    if normalized:
        return normalized + suffix

    normalized = _normalize_gpt(model_value)
    if normalized:
        return normalized + suffix

    return model.strip()


def estimate_cost_usd(
    *,
    model: str | None,
    provider: str | None,
    measurement_method: str | None,
    input_tokens: int | None,
    cached_input_tokens: int | None,
    output_tokens: int | None,
    pricing_resolution: PriceBookResolution | None = None,
) -> float | None:
    if measurement_method != "exact":
        return None

    total_input = int(input_tokens or 0)
    cached_input = int(cached_input_tokens or 0)
    total_output = int(output_tokens or 0)
    if total_input <= 0 and total_output <= 0 and cached_input <= 0:
        return None

    normalized = normalize_model_display(model, provider)
    lookup_name = _strip_parenthetical_suffix(normalized)
    resolution = pricing_resolution or resolve_price_book()
    profile = resolution.profiles.get(lookup_name)
    if profile is None:
        return None
    pricing = profile.pricing

    if _uses_disjoint_cached_input_tokens(normalized, provider):
        uncached_input = total_input
        cached_billable = cached_input
    else:
        cached_billable = min(cached_input, total_input)
        uncached_input = max(total_input - cached_billable, 0)
    cached_rate = pricing.cached_input_per_million
    if cached_rate is None:
        cached_rate = pricing.input_per_million

    estimate = (
        (uncached_input / 1_000_000) * pricing.input_per_million
        + (cached_billable / 1_000_000) * cached_rate
        + (total_output / 1_000_000) * pricing.output_per_million
    )
    return round(estimate, 8)


def _uses_disjoint_cached_input_tokens(model_label: str, provider: str | None) -> bool:
    provider_value = (provider or "").strip().lower()
    if provider_value in {"anthropic", "claude"}:
        return True
    return model_label.startswith("Claude ")


def _load_override_profiles(path: Path) -> dict[str, ModelPrice]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("pricing override must be a JSON object")

    raw_profiles = payload.get("profiles", payload)
    if not isinstance(raw_profiles, dict):
        raise ValueError("pricing override 'profiles' must be an object")

    profiles: dict[str, ModelPrice] = {}
    for model, raw_entry in raw_profiles.items():
        if not isinstance(model, str) or not model.strip():
            raise ValueError("pricing override keys must be non-empty model names")
        if not isinstance(raw_entry, dict):
            raise ValueError(f"pricing override for {model!r} must be an object")
        profiles[model.strip()] = ModelPrice(
            input_per_million=_read_required_float(raw_entry, "input_per_million", alias="input"),
            cached_input_per_million=_read_optional_float(raw_entry, "cached_input_per_million", alias="cached_input"),
            output_per_million=_read_required_float(raw_entry, "output_per_million", alias="output"),
        )
    return profiles


def _read_required_float(payload: dict[str, Any], key: str, *, alias: str | None = None) -> float:
    if key in payload:
        return float(payload[key])
    if alias and alias in payload:
        return float(payload[alias])
    raise ValueError(f"missing required field '{key}'")


def _read_optional_float(payload: dict[str, Any], key: str, *, alias: str | None = None) -> float | None:
    if key in payload:
        value = payload[key]
    elif alias and alias in payload:
        value = payload[alias]
    else:
        return None
    if value is None:
        return None
    return float(value)


def _strip_parenthetical_suffix(value: str) -> str:
    return _PAREN_SUFFIX_RE.sub("", value).strip()


def _normalize_claude(model: str) -> str | None:
    api_match = _CLAUDE_API_RE.match(model.replace("_", "-").strip())
    if api_match:
        family = api_match.group(1)
        version = api_match.group(2).replace("-", ".")
        tail = api_match.group(3)
        return f"Claude {family.title()} {version}{tail}".strip()

    match = _CLAUDE_PREFIX_RE.match(model)
    if not match:
        match = _CLAUDE_SUFFIX_RE.match(model)
        if not match:
            return None
        version = match.group(1)
        family = match.group(2)
        tail = match.group(3)
    else:
        family = match.group(1)
        version = match.group(2)
        tail = match.group(3)

    family_name = family.title()
    return f"Claude {family_name} {version}{tail}".strip()


def _normalize_gpt(model: str) -> str | None:
    normalized = model.replace("_", "-").strip()
    match = _GPT_RE.match(normalized)
    if not match:
        return None

    version = match.group(1)
    tier = match.group(2)
    tail = match.group(3)
    label = f"GPT-{version}"
    if tier:
        label += f" {tier.title()}"
    if tail:
        label += tail
    return label.strip()
