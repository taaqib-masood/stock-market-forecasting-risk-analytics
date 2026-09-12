"""
Holding-period presets — one daily engine, three holding horizons.
====================================================================
The system has ONE daily-bar signal engine. "Different trade types" is NOT a new
engine — it's the same signals exited on different schedules. Each preset is a
small bundle of risk parameters that the existing `RiskManager` already accepts
(`atr_multiplier` = stop width, `min_rr` = target distance) plus a `max_hold_days`
time-exit consumed by `src.auto_close`.

Intraday is deliberately absent: there is no intraday data path, and it is the
weakest halal ground. The horizons here are all multi-day, BUY-only swing holds.

A preset is only *blessed* (safe to rely on) once it clears the walk-forward
net-of-cost gate:  `python -m src.walk_forward --ticker RELIANCE --preset intra_month`.
`swing` is the existing validated baseline and is blessed in code; the others
start "unvalidated" and earn their badge by passing the gate (which writes the
result back into results/cockpit_config.json via `mark_validated`).

State lives in results/cockpit_config.json:
    {"preset": "swing", "validated": {"intra_month": {...stats}}}
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = Path("results/cockpit_config.json")

# id → display + risk params. atr_multiplier/min_rr are forwarded straight to
# RiskManager; max_hold_days is the time-based exit used by auto_close.
PRESETS: dict[str, dict] = {
    "intra_week": {
        "label": "Intra-week",
        "blurb": "Quick swings — tight stop, modest target, time-exit ~5 trading days.",
        "atr_multiplier": 1.2,
        "min_rr": 1.5,
        "max_hold_days": 5,
    },
    "swing": {
        "label": "Swing (default)",
        "blurb": "Balanced multi-week holds — the validated baseline.",
        "atr_multiplier": 2.0,
        "min_rr": 2.0,
        "max_hold_days": 15,
    },
    "intra_month": {
        "label": "Intra-month",
        "blurb": "Patient holds — wider stop, larger target, time-exit ~1 month.",
        "atr_multiplier": 2.5,
        "min_rr": 2.5,
        "max_hold_days": 22,
    },
}

DEFAULT = "swing"
# Blessed in code = already validated as the live baseline. Everything else must
# earn it through the walk-forward gate before the UI lets you lean on it.
_BLESSED = {"swing"}

# Only these keys are valid RiskManager kwargs — keep the rest out of rm_kwargs.
_RM_KEYS = ("atr_multiplier", "min_rr")


# ── lookups ────────────────────────────────────────────────────────────────────

def get(name: str | None = None) -> dict:
    """Preset bundle, falling back to the default for unknown names."""
    return PRESETS.get(name or DEFAULT, PRESETS[DEFAULT])


def rm_kwargs(name: str | None = None) -> dict:
    """The subset of a preset that RiskManager / backtest_with_risk accept."""
    p = get(name)
    return {k: p[k] for k in _RM_KEYS}


def max_hold_days(name: str | None = None) -> int:
    return int(get(name)["max_hold_days"])


# ── validation state ────────────────────────────────────────────────────────────

def is_validated(name: str) -> bool:
    """Blessed in code, or recorded as gate-passing in the config file."""
    if name in _BLESSED:
        return True
    return bool(_read().get("validated", {}).get(name))


def mark_validated(name: str, stats: dict | None = None) -> None:
    cfg = _read()
    cfg.setdefault("validated", {})[name] = stats or True
    _write(cfg)


def list_presets() -> list[dict]:
    """UI-friendly list: id, copy, params, and whether it's safe to rely on."""
    out = []
    for k, v in PRESETS.items():
        out.append({
            "id": k,
            "validated": is_validated(k),
            "active": k == active(),
            **{kk: v[kk] for kk in ("label", "blurb", "atr_multiplier",
                                    "min_rr", "max_hold_days")},
        })
    return out


# ── active selection ────────────────────────────────────────────────────────────

def active() -> str:
    name = _read().get("preset", DEFAULT)
    return name if name in PRESETS else DEFAULT


def set_active(name: str) -> str:
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose {list(PRESETS)}")
    cfg = _read()
    cfg["preset"] = name
    _write(cfg)
    return name


# ── persistence ─────────────────────────────────────────────────────────────────

def _read() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
