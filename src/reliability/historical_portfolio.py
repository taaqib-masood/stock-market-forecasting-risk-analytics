"""Point-in-time adapters for portfolio evaluation on retained NSE bars."""

from __future__ import annotations

import hashlib
import json
import math
from contextvars import ContextVar
import platform
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest_runner import run_backtest
from src.reliability.adjusted_prices import (
    CorporateActionError,
    _dividend_amounts,
    adjust_ohlcv,
    automatic_action_factor,
)
from src.reliability.corporate_action_reviews import (
    ReviewedFactorOverrides,
    load_reviewed_factor_overrides,
)
from src.reliability.experiment_preflight import (
    PreflightResult,
    resolve_task6_lookup_schema,
    verify_preflight_binding,
)
from src.reliability.experiment_registry import ExperimentRegistry
from src.reliability.preregistration import canonical_json_bytes, sha256_json
from src.reliability.portfolio_simulator import simulate_shared_portfolio
from src.reliability.residual_momentum import (
    allocate_weights,
    compute_scores,
    initial_stop,
    resolve_exit,
    select_candidates,
)
from src.reliability.statistics import bootstrap_excess_ci, evaluate_outperformance
from src.reliability.walk_forward import evaluate_regimes
from src.reliability.store import ReliabilityStore, _iso
from src.strategy import RuleStrategy, Strategy
from src.walk_forward import COST_PRESETS


class ResidualPortfolioDataError(ValueError):
    """Raised when retained point-in-time portfolio evidence is incomplete."""


_HALAL_CLASSIFICATION_MAX_AGE_DAYS = 365
_CORPORATE_ACTION_REVIEW_EXPERIMENTS = {
    "nse-halal-residual-momentum-v4",
    "nse-halal-residual-momentum-v5",
    "nse-halal-residual-momentum-v6",
    "nse-halal-residual-momentum-v7",
}
_ACTIVE_REVIEWED_FACTOR_OVERRIDES: ContextVar[ReviewedFactorOverrides | None] = ContextVar(
    "active_reviewed_factor_overrides",
    default=None,
)


def load_ohlcv(
    store: ReliabilityStore,
    symbol: str,
    *,
    start: str,
    end: str,
    as_of: str,
    bound_sessions: list[pd.Timestamp] | None = None,
    reviewed_factor_overrides: ReviewedFactorOverrides | None = None,
) -> pd.DataFrame:
    rows = store.connection.execute(
        """
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY symbol, session_date ORDER BY available_at DESC
            ) AS revision_rank
            FROM bars
            WHERE symbol = ? AND session_date >= ? AND session_date <= ?
              AND available_at <= ?
        )
        SELECT session_date, open, high, low, close, volume
        FROM ranked WHERE revision_rank = 1 ORDER BY session_date
        """,
        (symbol.upper(), _iso(start), _iso(end), _iso(as_of)),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    frame = pd.DataFrame([dict(row) for row in rows])
    frame.index = pd.DatetimeIndex(
        pd.to_datetime(frame.pop("session_date"), utc=True)
    ).tz_localize(None)
    frame = frame.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })[["Open", "High", "Low", "Close", "Volume"]]
    if bound_sessions is not None:
        allowed = pd.DatetimeIndex(bound_sessions)
        if allowed.tz is not None:
            allowed = allowed.tz_convert("UTC").tz_localize(None)
        frame = frame.loc[frame.index.isin(allowed)]
    actions = store.connection.execute(
        """
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY symbol, action_type, ex_date ORDER BY available_at DESC
            ) AS revision_rank
            FROM corporate_actions
            WHERE symbol = ? AND ex_date >= ? AND ex_date <= ? AND available_at <= ?
        )
        SELECT action_type, ex_date, payload_json
        FROM ranked WHERE revision_rank = 1 ORDER BY ex_date, action_type
        """,
        (symbol.upper(), _iso(start), _iso(end), _iso(as_of)),
    ).fetchall()
    adjustment_actions = []
    for row in actions:
        payload = json.loads(row["payload_json"])
        if row["action_type"] == "DIVIDEND" and isinstance(payload, dict):
            amount = payload.get("cash_amount")
            if amount is not None:
                try:
                    amount = float(amount)
                except (TypeError, ValueError) as exc:
                    raise CorporateActionError(
                        "invalid explicit DIVIDEND cash amount"
                    ) from exc
                if not math.isfinite(amount) or amount <= 0:
                    raise CorporateActionError(
                        "invalid explicit DIVIDEND cash amount"
                    )
                payload = {
                    **payload,
                    "purpose": f"Dividend - Rs {amount:.17g} Per Share",
                }
        adjustment_actions.append({
            "symbol": symbol.upper(),
            "action_type": row["action_type"],
            "ex_date": row["ex_date"][:10],
            "payload": payload,
        })
    binding = reviewed_factor_overrides or _ACTIVE_REVIEWED_FACTOR_OVERRIDES.get()
    return adjust_ohlcv(
        frame,
        adjustment_actions,
        reviewed_factor_overrides=binding,
    )


def select_liquid_universe(
    store: ReliabilityStore,
    *,
    through: str,
    limit: int,
    min_sessions: int = 200,
) -> list[str]:
    if limit < 1 or min_sessions < 1:
        raise ValueError("limit and min_sessions must be positive")
    rows = store.connection.execute(
        """
        SELECT symbol, COUNT(DISTINCT session_date) AS sessions,
               AVG(close * volume) AS average_turnover
        FROM bars WHERE session_date <= ? AND available_at <= ?
        GROUP BY symbol HAVING sessions >= ?
        ORDER BY average_turnover DESC, symbol ASC LIMIT ?
        """,
        (_iso(through), _iso(f"{through[:10]}T23:59:59Z"), min_sessions, limit),
    ).fetchall()
    return [row["symbol"] for row in rows]


def classify_benchmark_regimes(close: pd.Series) -> pd.Series:
    series = pd.Series(close, dtype=float).sort_index()
    known_close = series.shift(1)
    known_sma = series.rolling(200, min_periods=200).mean().shift(1)
    known_return = series.pct_change(60).shift(1)
    regimes = pd.Series("SIDEWAYS", index=series.index, dtype=object)
    regimes[(known_close > known_sma) & (known_return > 0)] = "BULL"
    regimes[(known_close < known_sma) & (known_return < 0)] = "BEAR"
    return regimes


def build_monthly_liquidity_universes(
    store: ReliabilityStore,
    *,
    start: str,
    end: str,
    limit: int,
    lookback_sessions: int = 60,
    min_sessions: int = 40,
) -> dict[str, list[str]]:
    if min(limit, lookback_sessions, min_sessions) < 1:
        raise ValueError("liquidity universe limits must be positive")
    rows = store.connection.execute(
        "SELECT DISTINCT session_date FROM bars WHERE session_date >= ? AND session_date <= ? "
        "ORDER BY session_date",
        (_iso(start), _iso(end)),
    ).fetchall()
    effective_dates = []
    seen_months = set()
    for row in rows:
        day = row["session_date"]
        month = day[:7]
        if month not in seen_months:
            seen_months.add(month)
            effective_dates.append(day)

    output = {}
    for effective in effective_dates:
        prior = store.connection.execute(
            "SELECT DISTINCT session_date FROM bars WHERE session_date < ? "
            "ORDER BY session_date DESC LIMIT ?",
            (effective, lookback_sessions),
        ).fetchall()
        if len(prior) < min_sessions:
            output[effective[:10]] = []
            continue
        window_start = prior[-1]["session_date"]
        ranked = store.connection.execute(
            """
            SELECT symbol, COUNT(DISTINCT session_date) AS sessions,
                   AVG(close * volume) AS average_turnover
            FROM bars
            WHERE session_date >= ? AND session_date < ? AND available_at < ?
            GROUP BY symbol HAVING sessions >= ?
            ORDER BY average_turnover DESC, symbol ASC LIMIT ?
            """,
            (window_start, effective, effective, min_sessions, limit),
        ).fetchall()
        output[effective[:10]] = [row["symbol"] for row in ranked]
    return output


def filter_trades_by_monthly_universe(
    trades: pd.DataFrame,
    universes: dict[str, list[str]],
) -> pd.DataFrame:
    if trades.empty or not universes:
        return trades.iloc[0:0].copy()
    effective = [(pd.Timestamp(day), set(symbols)) for day, symbols in sorted(universes.items())]
    keep = []
    for _, trade in trades.iterrows():
        signal_day = pd.Timestamp(trade["signal_date"])
        applicable = [symbols for day, symbols in effective if day <= signal_day]
        keep.append(bool(applicable and trade["ticker"] in applicable[-1]))
    return trades.loc[keep].reset_index(drop=True)


def filter_trades_by_regime(
    trades: pd.DataFrame,
    regimes: pd.Series,
    *,
    allowed: set[str],
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    regime_series = pd.Series(regimes).copy()
    regime_series.index = pd.to_datetime(regime_series.index)
    keep = []
    for _, trade in trades.iterrows():
        day = pd.Timestamp(trade["signal_date"])
        value = regime_series.get(day)
        keep.append(value in allowed)
    return trades.loc[keep].reset_index(drop=True)


def run_static_universe_diagnostic(
    store: ReliabilityStore,
    symbols: list[str],
    *,
    start: str,
    end: str,
    test_start: str,
    benchmark_symbol: str = "NIFTYBEES",
    strategy: Strategy | None = None,
    initial_capital: float = 100_000.0,
    max_positions: int = 10,
    max_position_fraction: float = 0.10,
    statistical_policy: dict | None = None,
    entry_universes: dict[str, list[str]] | None = None,
    allowed_entry_regimes: set[str] | None = None,
) -> dict:
    strategy = strategy or RuleStrategy()
    as_of = f"{end[:10]}T23:59:59Z"
    logs = []
    closes = {}
    evaluated = []
    for symbol in symbols:
        frame = load_ohlcv(store, symbol, start=start, end=end, as_of=as_of)
        if len(frame) < 220:
            continue
        result = run_backtest(
            frame, strategy=strategy, fetch_context=False,
            capital=initial_capital, **COST_PRESETS["nse_delivery"],
        )
        log = result["trade_log"].copy()
        if not log.empty:
            log = log[pd.to_datetime(log["entry_date"]) >= pd.Timestamp(test_start)]
            if not log.empty:
                log["ticker"] = symbol
                logs.append(log)
        closes[symbol] = frame["Close"]
        evaluated.append(symbol)

    benchmark = load_ohlcv(
        store, benchmark_symbol, start=start, end=end, as_of=as_of
    )["Close"]
    benchmark_regimes = classify_benchmark_regimes(benchmark)
    prices = pd.DataFrame(closes).sort_index().loc[pd.Timestamp(test_start):]
    trades = pd.concat(logs, ignore_index=True) if logs else pd.DataFrame()
    candidate_completed = len(trades)
    if entry_universes is not None:
        trades = filter_trades_by_monthly_universe(trades, entry_universes)
    if allowed_entry_regimes is not None:
        trades = filter_trades_by_regime(
            trades, benchmark_regimes, allowed=allowed_entry_regimes
        )
    portfolio = simulate_shared_portfolio(
        trades, prices, initial_capital=initial_capital,
        max_positions=max_positions, max_position_fraction=max_position_fraction,
    )
    benchmark_returns = benchmark.pct_change().reindex(portfolio["returns"].index).fillna(0.0)
    policy = dict(statistical_policy or {})
    overall = evaluate_outperformance(portfolio["returns"], benchmark_returns, policy=policy)
    regimes = benchmark_regimes.reindex(portfolio["returns"].index)
    regime_result = evaluate_regimes(
        portfolio["returns"], benchmark_returns, regimes, policy=policy
    )
    return {
        "evaluated_symbols": evaluated,
        "candidate_completed_trades": candidate_completed,
        "completed_trades": len(trades),
        "portfolio": portfolio,
        "benchmark_returns": benchmark_returns,
        "overall": overall,
        "regimes": regime_result,
    }


def _residual_error(code: str, symbol: str | None = None) -> ResidualPortfolioDataError:
    return ResidualPortfolioDataError(code if symbol is None else f"{code}:{symbol}")


def _residual_timestamp(day: pd.Timestamp, *, close: bool = True) -> str:
    suffix = "10:00:00Z" if close else "03:45:00Z"
    return f"{day.date().isoformat()}T{suffix}"


def _residual_lookup_schema(store: ReliabilityStore):
    try:
        return resolve_task6_lookup_schema(store)
    except ValueError as exc:
        raise _residual_error("PREFLIGHT_STORE_MANIFESTS") from exc


def _residual_sector(store: ReliabilityStore, symbol: str, as_of: str) -> str:
    lookup = _residual_lookup_schema(store).sector
    row = store.connection.execute(
        f"""
        SELECT {lookup.value_column} FROM {lookup.table}
        WHERE symbol = ? AND {lookup.effective_column} <= ?
          AND available_at <= ?
        ORDER BY {lookup.effective_column} DESC, available_at DESC LIMIT 1
        """,
        (symbol, as_of, as_of),
    ).fetchone()
    if (
        row is not None
        and isinstance(row[lookup.value_column], str)
        and row[lookup.value_column].strip()
    ):
        return row[lookup.value_column].strip()
    return ""


def _residual_event_active(store: ReliabilityStore, table: str, symbol: str, as_of: str) -> bool:
    schema = _residual_lookup_schema(store)
    lookups = {
        "suspensions": schema.suspensions,
        "delistings": schema.delistings,
    }
    lookup = lookups.get(table)
    if lookup is None:
        raise _residual_error(f"MISSING_{table.upper()}_SOURCE")
    row = store.connection.execute(
        f"""
        SELECT 1 FROM {lookup.table}
        WHERE symbol = ? AND {lookup.effective_column} <= ?
          AND available_at <= ?
        ORDER BY {lookup.effective_column} DESC, available_at DESC LIMIT 1
        """,
        (symbol, as_of, as_of),
    ).fetchone()
    return row is not None


def _residual_fundamental(store: ReliabilityStore, symbol: str, as_of: str) -> dict | None:
    row = store.connection.execute(
        """
        SELECT debt_to_assets, interest_income_ratio, payload_json
        FROM fundamentals
        WHERE symbol = ? AND period_end <= ? AND available_at <= ?
        ORDER BY period_end DESC, available_at DESC LIMIT 1
        """,
        (symbol, as_of, as_of),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        return None
    return {
        "debt_to_assets": row["debt_to_assets"],
        "interest_income_ratio": row["interest_income_ratio"],
        "payload": payload if isinstance(payload, dict) else {},
    }


def _residual_halal(
    store: ReliabilityStore,
    symbol: str,
    as_of: str,
) -> dict:
    point = _iso(as_of)
    rows = store.connection.execute(
        """
        SELECT tier, tradeable, ruleset_version, reason, effective_from,
               available_at, manifest_hash
        FROM halal_classifications
        WHERE symbol = ? AND effective_from <= ? AND available_at <= ?
        ORDER BY effective_from DESC, available_at DESC
        """,
        (symbol.upper(), point, point),
    ).fetchall()
    if rows:
        top_effective = rows[0]["effective_from"]
        top_available = rows[0]["available_at"]
        top_revisions = {
            (
                row["tier"],
                row["tradeable"],
                row["ruleset_version"],
                row["reason"],
                row["manifest_hash"],
            )
            for row in rows
            if row["effective_from"] == top_effective
            and row["available_at"] == top_available
        }
        if len(top_revisions) > 1:
            raise _residual_error("CONFLICTING_HALAL", symbol)
    halal = store.halal_as_of(
        symbol,
        as_of,
        max_age_days=_HALAL_CLASSIFICATION_MAX_AGE_DAYS,
    )
    if halal.get("reason") == "halal classification is stale":
        raise _residual_error("STALE_HALAL", symbol)
    return halal


def _residual_eligible(store: ReliabilityStore, symbol: str, as_of: str, parameters: dict) -> tuple[str, float]:
    max_age = parameters.get(
        "halal_max_age_days",
        _HALAL_CLASSIFICATION_MAX_AGE_DAYS,
    )
    if (
        isinstance(max_age, bool)
        or max_age != _HALAL_CLASSIFICATION_MAX_AGE_DAYS
    ):
        raise _residual_error("INVALID_HALAL_FRESHNESS_POLICY", symbol)
    halal = _residual_halal(store, symbol, as_of)
    if halal.get("tier") == "UNKNOWN":
        raise _residual_error("MISSING_HALAL", symbol)
    if not halal.get("tradeable"):
        return "", 0.0
    fundamental = _residual_fundamental(store, symbol, as_of)
    if fundamental is None:
        raise _residual_error("MISSING_FUNDAMENTAL", symbol)
    debt = fundamental["debt_to_assets"]
    interest = fundamental["interest_income_ratio"]
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (debt, interest)):
        raise _residual_error("MISSING_FUNDAMENTAL", symbol)
    if debt > float(parameters.get("max_debt_to_assets", 0.33)):
        return "", 0.0
    if interest > float(parameters.get("max_interest_income_ratio", 0.05)):
        return "", 0.0
    sector = _residual_sector(store, symbol, as_of)
    if not sector:
        raise _residual_error("MISSING_SECTOR", symbol)
    liquidity = parameters.get("liquidity_cap", 0.05)
    if not isinstance(liquidity, (int, float)) or not math.isfinite(liquidity) or not 0 < liquidity <= 0.05:
        raise _residual_error("INVALID_LIQUIDITY_CAP", symbol)
    return sector, float(liquidity)


def _residual_bar(store: ReliabilityStore, symbol: str, day: pd.Timestamp, as_of: str) -> dict:
    frame = _residual_load_ohlcv(
        store, symbol, start=day.date().isoformat(), end=day.date().isoformat(), as_of=as_of
    )
    if frame.empty or day not in frame.index:
        raise _residual_error("MISSING_NEXT_OPEN", symbol)
    row = frame.loc[day]
    values = {name.lower(): float(row[name]) for name in ("Open", "High", "Low", "Close")}
    if not all(math.isfinite(value) and value > 0 for value in values.values()):
        raise _residual_error("MISSING_NEXT_OPEN", symbol)
    return values


def _residual_load_ohlcv(
    store: ReliabilityStore,
    symbol: str,
    *,
    start: str,
    end: str,
    as_of: str,
    bound_sessions: list[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    try:
        return load_ohlcv(
            store,
            symbol,
            start=start,
            end=end,
            as_of=as_of,
            bound_sessions=bound_sessions,
        )
    except CorporateActionError as exc:
        raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR", symbol) from exc


def _residual_atr(frame: pd.DataFrame, length: int) -> float:
    if length < 1 or len(frame) < length + 1:
        raise _residual_error("MISSING_ATR")
    high, low, close = frame["High"], frame["Low"], frame["Close"]
    true_range = pd.concat([
        high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    value = float(true_range.tail(length).mean())
    if not math.isfinite(value) or value <= 0:
        raise _residual_error("MISSING_ATR")
    return value


def _residual_benchmark(benchmark_tri: pd.Series, sessions: list[pd.Timestamp]) -> pd.Series:
    if not isinstance(benchmark_tri, pd.Series) or benchmark_tri.empty:
        raise _residual_error("MISSING_BENCHMARK_SESSION")
    series = pd.Series(benchmark_tri, dtype=float).copy()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    if series.index.has_duplicates or not series.index.is_monotonic_increasing:
        raise _residual_error("MISSING_BENCHMARK_SESSION")
    required = pd.DatetimeIndex(sessions)
    missing = required.difference(series.index)
    if len(missing) or not np.isfinite(series.reindex(required)).all() or (series.reindex(required) <= 0).any():
        raise _residual_error("MISSING_BENCHMARK_SESSION")
    return series.reindex(required)


def _residual_weekly_decisions(
    sessions: list[pd.Timestamp],
    closures: list[pd.Timestamp],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> set[pd.Timestamp]:
    scoped = [day for day in sessions if start <= day <= end]
    known_dates = {
        pd.Timestamp(day).normalize() for day in sessions + closures
    }
    final_by_week: dict[tuple[int, int], pd.Timestamp] = {}
    for day in scoped:
        iso = day.isocalendar()
        final_by_week[(iso.year, iso.week)] = day
    decisions = set()
    for day in final_by_week.values():
        remaining_weekdays = [
            day + pd.Timedelta(days=offset)
            for offset in range(1, 5 - day.weekday())
        ]
        if all(
            candidate.normalize() in known_dates
            for candidate in remaining_weekdays
        ):
            decisions.add(day)
    return decisions


def _residual_protocol(protocol: dict) -> tuple[dict, dict, pd.Timestamp, pd.Timestamp]:
    if not isinstance(protocol, dict) or not isinstance(protocol.get("parameters"), dict):
        raise _residual_error("INVALID_PROTOCOL")
    try:
        scored = protocol["periods"]["scored"]
        start, end = pd.Timestamp(scored[0]), pd.Timestamp(scored[1])
    except (KeyError, TypeError, ValueError, IndexError):
        raise _residual_error("INVALID_PROTOCOL") from None
    if start > end:
        raise _residual_error("INVALID_PROTOCOL")
    return protocol["parameters"], protocol.get("statistical_policy", {}), start, end


def _canonical_report_value(value):
    if isinstance(value, pd.Series):
        return {
            "index": [_canonical_report_value(item) for item in value.index],
            "name": _canonical_report_value(value.name),
            "values": [_canonical_report_value(item) for item in value.tolist()],
        }
    if isinstance(value, pd.DataFrame):
        return {
            "columns": [str(column) for column in value.columns],
            "index": [_canonical_report_value(item) for item in value.index],
            "values": [
                [_canonical_report_value(item) for item in row]
                for row in value.to_numpy().tolist()
            ],
        }
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_report_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_report_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonical_report_value(item) for item in value)
    return value


def _canonical_report_core_bytes(report_core: dict) -> bytes:
    return canonical_json_bytes(_canonical_report_value(report_core))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _store_snapshot(store: ReliabilityStore) -> dict:
    tables = store.connection.execute(
        """
        SELECT name, sql FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    snapshot = {}
    for table in tables:
        name = table["name"]
        columns = [
            row["name"]
            for row in store.connection.execute(
                f"PRAGMA table_info({_quoted_identifier(name)})"
            ).fetchall()
        ]
        quoted_columns = ", ".join(_quoted_identifier(column) for column in columns)
        query = f"SELECT {quoted_columns} FROM {_quoted_identifier(name)}"
        if columns:
            query += " ORDER BY " + quoted_columns
        rows = store.connection.execute(query).fetchall()
        snapshot[name] = {
            "columns": columns,
            "rows": [
                [_canonical_report_value(row[column]) for column in columns]
                for row in rows
            ],
            "schema": table["sql"],
        }
    return snapshot


def _store_evidence(store: ReliabilityStore) -> dict:
    snapshot = _store_snapshot(store)
    manifests = snapshot.get("manifests", {}).get("rows", [])
    manifest_columns = snapshot.get("manifests", {}).get("columns", [])
    content_hash_index = (
        manifest_columns.index("content_hash")
        if "content_hash" in manifest_columns
        else None
    )
    manifest_hashes = (
        sorted(row[content_hash_index] for row in manifests)
        if content_hash_index is not None
        else []
    )
    return {
        "store_manifest_sha256s": manifest_hashes,
        "store_manifests_sha256": sha256_json(
            {"columns": manifest_columns, "rows": manifests}
        ),
        "store_snapshot_sha256": sha256_json(snapshot),
    }


def _registry_snapshot_sha256(registry: ExperimentRegistry) -> str:
    return _sha256_bytes(
        registry.path.read_bytes() if registry.path.exists() else b""
    )


def _code_evidence() -> dict:
    root = Path(__file__).resolve().parents[2]
    paths = (
        "src/reliability/adjusted_prices.py",
        "src/reliability/experiment_preflight.py",
        "src/reliability/experiment_registry.py",
        "src/reliability/historical_portfolio.py",
        "src/reliability/nifty_tri.py",
        "src/reliability/preregistration.py",
        "src/reliability/residual_momentum.py",
        "src/reliability/residual_momentum_experiment.py",
        "src/reliability/statistics.py",
        "src/reliability/store.py",
    )
    files = {
        relative: _sha256_bytes((root / relative).read_bytes())
        for relative in paths
    }
    return {"code_manifest": files, "code_sha256": sha256_json(files)}


def _environment_manifest() -> dict:
    packages = {}
    for package in ("numpy", "pandas", "scipy"):
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = "NOT_INSTALLED"
    return {
        "implementation": platform.python_implementation(),
        "packages": packages,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
    }


def _benchmark_input_payload(benchmark_tri: pd.Series) -> list[dict]:
    if not isinstance(benchmark_tri, pd.Series):
        raise _residual_error("MISSING_BENCHMARK_SESSION")
    return [
        {
            "date": pd.Timestamp(day).date().isoformat(),
            "value": float(value),
        }
        for day, value in benchmark_tri.items()
    ]


def _coverage_verified(aggregates: Mapping) -> bool:
    coverage = aggregates.get("coverage")
    if not isinstance(coverage, Mapping) or not coverage:
        return False
    for aggregate in coverage.values():
        if not isinstance(aggregate, Mapping):
            return False
        ratio = aggregate.get("ratio")
        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not math.isfinite(float(ratio))
            or float(ratio) != 1.0
        ):
            return False
    return True


def _preflight_evidence(
    store: ReliabilityStore,
    preflight,
    protocol: dict,
) -> dict:
    if (
        not isinstance(preflight, PreflightResult)
        or not preflight.passed
        or preflight.blockers
    ):
        raise _residual_error("PREFLIGHT_FAILED")
    if not _valid_sha256(preflight.dataset_manifest_sha256):
        raise _residual_error("PREFLIGHT_DATASET")
    try:
        binding = verify_preflight_binding(store, protocol, preflight)
    except ValueError as exc:
        raise _residual_error(str(exc)) from exc
    aggregates = preflight.aggregates
    data_coverage_verified = _coverage_verified(aggregates)
    if not data_coverage_verified:
        raise _residual_error("PREFLIGHT_COVERAGE")
    source_hashes = sorted(binding["source_hashes"])
    catalogue_hashes = sorted(binding["catalogue_hashes"])
    review_hashes = sorted(binding["review_hashes"])
    store_manifest_hashes = {
        domain: sorted(hashes)
        for domain, hashes in binding["store_manifest_hashes"].items()
    }
    aggregate_hash = sha256_json(_canonical_report_value(aggregates))
    return {
        "calendar_closures": list(binding["closures"]),
        "calendar_sessions": list(binding["sessions"]),
        "dataset_manifest_sha256": binding["dataset_manifest_sha256"],
        "preflight_aggregates_sha256": aggregate_hash,
        "protocol_sha256": binding["protocol_sha256"],
        "source_sha256s": source_hashes,
        "catalogue_sha256s": catalogue_hashes,
        "retained_source_sha256s": sorted(
            set(source_hashes) | set(catalogue_hashes)
        ),
        "review_report_sha256s": review_hashes,
        "preflight_store_manifest_sha256s": store_manifest_hashes,
        "verification": {
            "data_coverage_verified": data_coverage_verified,
            "source_hashes_verified": True,
            "review_queue_verified": True,
        },
    }


def _input_manifest(
    store: ReliabilityStore,
    *,
    protocol: dict,
    benchmark_tri: pd.Series,
    preflight_evidence: dict,
    registry: ExperimentRegistry,
    n_trials: int,
) -> dict:
    environment = _environment_manifest()
    evidence = {
        "benchmark_input_sha256": sha256_json(
            _benchmark_input_payload(benchmark_tri)
        ),
        "calendar_closures": preflight_evidence["calendar_closures"],
        "calendar_sessions": preflight_evidence["calendar_sessions"],
        "dataset_manifest_sha256": preflight_evidence[
            "dataset_manifest_sha256"
        ],
        "environment_manifest": environment,
        "environment_manifest_sha256": sha256_json(environment),
        "preflight_aggregates_sha256": preflight_evidence[
            "preflight_aggregates_sha256"
        ],
        "protocol_sha256": preflight_evidence["protocol_sha256"],
        "effective_n_trials": n_trials,
        "registry_snapshot_sha256": _registry_snapshot_sha256(registry),
        "source_sha256s": preflight_evidence["source_sha256s"],
        "catalogue_sha256s": preflight_evidence["catalogue_sha256s"],
        "retained_source_sha256s": preflight_evidence[
            "retained_source_sha256s"
        ],
        "review_report_sha256s": preflight_evidence[
            "review_report_sha256s"
        ],
        "preflight_store_manifest_sha256s": preflight_evidence[
            "preflight_store_manifest_sha256s"
        ],
    }
    evidence.update(_code_evidence())
    evidence.update(_store_evidence(store))
    evidence["dataset_preflight_binding_sha256"] = sha256_json(
        {
            "calendar_closures": evidence["calendar_closures"],
            "calendar_sessions": evidence["calendar_sessions"],
            "dataset_manifest_sha256": evidence["dataset_manifest_sha256"],
            "preflight_aggregates_sha256": evidence[
                "preflight_aggregates_sha256"
            ],
            "source_sha256s": evidence["source_sha256s"],
            "catalogue_sha256s": evidence["catalogue_sha256s"],
            "retained_source_sha256s": evidence[
                "retained_source_sha256s"
            ],
            "review_report_sha256s": evidence[
                "review_report_sha256s"
            ],
            "preflight_store_manifest_sha256s": evidence[
                "preflight_store_manifest_sha256s"
            ],
        }
    )
    return evidence


def _simulation_source_hashes(preflight_evidence: dict) -> dict:
    return {
        "calendar_closures": preflight_evidence["calendar_closures"],
        "calendar_sessions": preflight_evidence["calendar_sessions"],
        "dataset_manifest": preflight_evidence[
            "dataset_manifest_sha256"
        ],
        "preflight_aggregates": preflight_evidence[
            "preflight_aggregates_sha256"
        ],
        "protocol": preflight_evidence["protocol_sha256"],
        "sources": preflight_evidence["source_sha256s"],
        "catalogues": preflight_evidence["catalogue_sha256s"],
        "retained": preflight_evidence["retained_source_sha256s"],
        "reviews": preflight_evidence["review_report_sha256s"],
        "store_manifests": preflight_evidence[
            "preflight_store_manifest_sha256s"
        ],
    }


def _realized_gate_failures(exposure: dict, verification: dict) -> list[str]:
    failures = []
    for metric, threshold, gate in (
        ("max_gross", 0.80, "realized_gross"),
        ("max_security", 0.10, "realized_security"),
        ("max_sector", 0.30, "realized_sector"),
        ("max_correlation", 0.80, "selected_correlation"),
        ("max_participation", 0.05, "order_participation"),
    ):
        if float(exposure.get(metric, math.inf)) > threshold:
            failures.append(gate)
    for field, gate in (
        ("data_coverage_verified", "data_coverage"),
        ("source_hashes_verified", "source_hashes"),
        ("review_queue_verified", "review_queue"),
        ("order_queue_verified", "order_queue"),
        ("reproducibility_verified", "reproducibility"),
    ):
        if verification.get(field) is not True:
            failures.append(gate)
    return failures


def _pit_bar(store: ReliabilityStore, symbol: str, day: pd.Timestamp, as_of: str) -> dict:
    row = store.connection.execute(
        """
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY symbol, session_date ORDER BY available_at DESC
            ) AS revision_rank
            FROM bars WHERE symbol = ? AND session_date = ? AND available_at <= ?
        )
        SELECT open, high, low, close, volume FROM ranked WHERE revision_rank = 1
        """, (symbol, _iso(day), _iso(as_of)),
    ).fetchone()
    if row is None:
        raise _residual_error("MISSING_BAR", symbol)
    values = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
    if (not all(math.isfinite(value) and value > 0 for value in values.values())
            or values["low"] > min(values["open"], values["close"])
            or values["high"] < max(values["open"], values["close"])):
        raise _residual_error("MALFORMED_OHLC", symbol)
    return values


def _pit_dividend_amount(
    store: ReliabilityStore,
    symbol: str,
    day: pd.Timestamp,
    as_of: str,
    payload: dict,
    sessions: list[pd.Timestamp],
) -> float:
    if payload.get("cash_amount") is not None:
        try:
            amount = float(payload["cash_amount"])
        except (TypeError, ValueError):
            raise _residual_error(
                "MISSING_CORPORATE_ACTION_FACTOR", symbol
            ) from None
    else:
        values = _dividend_amounts(str(payload.get("purpose", "")))
        if not values:
            raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR", symbol)
        amount = sum(values)
    if not math.isfinite(amount) or amount <= 0:
        raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR", symbol)
    return amount


def _pit_actions(
    store: ReliabilityStore,
    symbol: str,
    day: pd.Timestamp,
    as_of: str,
    sessions: list[pd.Timestamp],
) -> list[dict]:
    rows = store.connection.execute(
        """
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY symbol, action_type, ex_date ORDER BY available_at DESC
            ) AS revision_rank
            FROM corporate_actions
            WHERE symbol = ? AND ex_date = ? AND available_at <= ?
        )
        SELECT action_type, payload_json FROM ranked WHERE revision_rank = 1 ORDER BY action_type
        """, (symbol, _iso(day), _iso(as_of)),
    ).fetchall()
    output = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            raise _residual_error(
                "MISSING_CORPORATE_ACTION_FACTOR", symbol
            ) from None
        if not isinstance(payload, dict):
            raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR", symbol)
        if row["action_type"] == "DIVIDEND":
            output.append({
                "amount": _pit_dividend_amount(
                    store,
                    symbol,
                    day,
                    as_of,
                    payload,
                    sessions,
                ),
                "action_type": "DIVIDEND",
            })
            continue
        if row["action_type"] not in {"SPLIT", "BONUS"}:
            raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR", symbol)
        try:
            factor, _ = automatic_action_factor({
                "action_type": row["action_type"],
                "payload": payload,
            })
        except CorporateActionError:
            raise _residual_error(
                "MISSING_CORPORATE_ACTION_FACTOR", symbol
            ) from None
        if not 0 < factor <= 1:
            raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR", symbol)
        output.append({"factor": factor, "action_type": row["action_type"]})
    return output


def _pit_open_eligible(store: ReliabilityStore, symbol: str, timestamp: str, parameters: dict) -> tuple[str, float]:
    if symbol not in store.eligible_universe(timestamp):
        return "", 0.0
    sector, _ = _residual_eligible(store, symbol, timestamp, parameters)
    if not sector:
        return "", 0.0
    if _residual_event_active(store, "suspensions", symbol, timestamp):
        return "", 0.0
    if _residual_event_active(store, "delistings", symbol, timestamp):
        return "", 0.0
    return sector, 1.0


def _pit_trailing_traded_value(
    store: ReliabilityStore,
    symbol: str,
    through_day: pd.Timestamp,
    as_of: str,
    sessions: list[pd.Timestamp],
    *,
    include_through_day: bool,
) -> float:
    prior = [
        day
        for day in sessions
        if day <= through_day
        if include_through_day or day < through_day
    ][-60:]
    if len(prior) < 1:
        raise _residual_error("MISSING_CANDIDATE_HISTORY", symbol)
    values = []
    for day in prior:
        bar = _pit_bar(store, symbol, day, as_of)
        values.append(bar["close"] * bar["volume"])
    result = float(np.median(values))
    if not math.isfinite(result) or result <= 0:
        raise _residual_error("MISSING_CANDIDATE_HISTORY", symbol)
    return result


def _pit_trailing_liquidity(
    store: ReliabilityStore, symbol: str, decision_day: pd.Timestamp, decision_as_of: str,
    sessions: list[pd.Timestamp],
) -> float:
    return _pit_trailing_traded_value(
        store,
        symbol,
        decision_day,
        decision_as_of,
        sessions,
        include_through_day=True,
    )


def _selected_pairwise_correlation(
    returns: pd.DataFrame,
    selected: list[str],
    *,
    lookback: int,
) -> float:
    if len(selected) < 2:
        return 0.0
    correlations = returns[selected].tail(lookback).corr()
    mask = ~np.eye(len(selected), dtype=bool)
    values = correlations.where(mask).stack()
    if values.empty:
        return 0.0
    result = float(values.max())
    if not math.isfinite(result):
        return 0.0
    return result


def _position_exposure(
    positions: dict,
    prices: dict[str, float],
    cash: float,
) -> dict:
    values = {
        symbol: position["shares"] * prices[symbol]
        for symbol, position in positions.items()
    }
    nav = cash + sum(values.values())
    sector_values = {}
    for symbol, value in values.items():
        sector = positions[symbol]["sector"]
        sector_values[sector] = sector_values.get(sector, 0.0) + value
    return {
        "nav": nav,
        "position_values": values,
        "gross": 0.0 if nav <= 0 else sum(values.values()) / nav,
        "max_security": (
            0.0 if nav <= 0 else max(values.values(), default=0.0) / nav
        ),
        "max_sector": (
            0.0
            if nav <= 0
            else max(sector_values.values(), default=0.0) / nav
        ),
    }


def _pit_open_exit(bar: dict, position: dict, *, forced: bool, rank_exit: bool) -> tuple[str, float] | None:
    if bar["open"] < position["stop"]:
        return "stop", bar["open"]
    if forced:
        return "forced_exit", bar["open"]
    if rank_exit:
        return "rank_exit", bar["open"]
    if position["held_sessions"] >= 20:
        return "max_hold", bar["open"]
    return None


def _pit_regimes(strategy: pd.Series, benchmark: pd.Series, regimes: pd.Series, policy: dict) -> dict:
    results = {}
    for regime in ("BULL", "BEAR", "SIDEWAYS"):
        frame = pd.concat([strategy, benchmark, regimes], axis=1).dropna()
        subset = frame[frame.iloc[:, 2] == regime]
        if subset.empty:
            results[regime] = {"passed": False, "failed_gates": ["missing_regime"], "metrics": {"observations": 0}}
            continue
        excess = subset.iloc[:, 0] - subset.iloc[:, 1]
        ci = bootstrap_excess_ci(subset.iloc[:, 0], subset.iloc[:, 1], n_boot=max(100, int(policy["bootstrap_samples"])), confidence=0.80)
        equity = (1.0 + subset.iloc[:, 0]).cumprod()
        drawdown = abs(float((equity / equity.cummax() - 1).min()))
        failed = []
        if len(subset) < 126:
            failed.append("minimum_observations")
        if ci["mean"] <= 0:
            failed.append("annualized_excess_return")
        if ci["probability_positive"] < 0.80:
            failed.append("probability_outperformance")
        if drawdown > 0.15:
            failed.append("max_drawdown")
        results[regime] = {"passed": not failed, "failed_gates": failed, "metrics": {"observations": len(subset), "annualized_excess_return": ci["mean"], "probability_outperformance": ci["probability_positive"], "max_drawdown": drawdown}}
    return {"passed": all(result["passed"] for result in results.values()), "regimes": results}


def _run_residual_momentum_once(
    store: ReliabilityStore,
    *,
    protocol: dict,
    benchmark_tri: pd.Series,
    calendar_sessions: list[str],
    calendar_closures: list[str],
    n_trials: int,
    source_hashes: dict,
) -> dict:
    """Run one read-only deterministic simulation pass."""
    parameters, statistical_policy, scored_start, scored_end = _residual_protocol(protocol)
    warmup_start = pd.Timestamp(protocol["periods"]["warmup"][0])
    sessions = [
        pd.Timestamp(day)
        for day in calendar_sessions
        if warmup_start <= pd.Timestamp(day) <= scored_end
    ]
    closures = [pd.Timestamp(day) for day in calendar_closures]
    benchmark = _residual_benchmark(benchmark_tri, sessions)
    if not sessions or scored_start not in sessions:
        raise _residual_error("MISSING_BENCHMARK_SESSION")
    decision_days = _residual_weekly_decisions(
        sessions,
        closures,
        scored_start,
        scored_end,
    )
    long_lag, skip = int(parameters.get("momentum_long", 252)), int(parameters.get("skip", 21))
    if long_lag <= skip or skip < 1:
        raise _residual_error("INVALID_PROTOCOL")
    capital = float(parameters.get("initial_capital", 100_000.0))
    if not math.isfinite(capital) or capital <= 0:
        raise _residual_error("INVALID_PROTOCOL")
    positions, pending = {}, {}
    cash, trade_notional, cost_notional, fees_paid = capital, 0.0, 0.0, 0.0
    decisions, trades, rejected, daily, ledger = [], [], [], [], []
    selected_correlations = []
    buy_participations, sell_participations = [], []
    targets: set[str] = set()

    for index, day in enumerate(sessions):
        starting_cash = cash
        open_time, close_time = _residual_timestamp(day, close=False), _residual_timestamp(day)
        bars = {
            symbol: _pit_bar(store, symbol, day, open_time)
            for symbol in sorted(positions)
        }
        for symbol, position in list(positions.items()):
            for action in _pit_actions(
                store,
                symbol,
                day,
                open_time,
                sessions,
            ):
                if action["action_type"] == "DIVIDEND":
                    credit = position["shares"] * action["amount"]
                    cash += credit
                    ledger.append({
                        "kind": "DIVIDEND",
                        "date": day.date().isoformat(),
                        "ticker": symbol,
                        "shares": position["shares"],
                        "cash_amount_per_share": action["amount"],
                        "amount": credit,
                        "cash": cash,
                    })
                    continue
                factor = action["factor"]
                before = {
                    "shares": position["shares"],
                    "stop": position["stop"],
                    "entry_price": position["entry_price"],
                    "cost_basis": position["cost_basis"],
                }
                position["shares"] /= factor
                position["stop"] *= factor
                position["entry_price"] *= factor
                position["cost_basis"] *= factor
                ledger.append({
                    "kind": "ACTION",
                    "date": day.date().isoformat(),
                    "ticker": symbol,
                    "action_type": action["action_type"],
                    "factor": factor,
                    "shares_before": before["shares"],
                    "shares_after": position["shares"],
                    "stop_before": before["stop"],
                    "stop_after": position["stop"],
                    "entry_price_before": before["entry_price"],
                    "entry_price_after": position["entry_price"],
                    "cost_basis_before": before["cost_basis"],
                    "cost_basis_after": position["cost_basis"],
                    "cash": cash,
                })
            forced = not bool(_pit_open_eligible(store, symbol, open_time, parameters)[0])
            exit_fill = _pit_open_exit(bars[symbol], position, forced=forced, rank_exit=symbol not in targets)
            if exit_fill is not None:
                reason, price = exit_fill
                proceeds = position["shares"] * price
                fee = proceeds * 0.0015
                cash += proceeds - fee
                trade_notional += proceeds
                cost_notional += proceeds
                fees_paid += fee
                traded_value = _pit_trailing_traded_value(
                    store,
                    symbol,
                    day,
                    open_time,
                    sessions,
                    include_through_day=False,
                )
                participation = proceeds / traded_value
                sell_participations.append(participation)
                exit_reason = "gap_stop" if reason == "stop" else reason
                trades.append({
                    **position,
                    "ticker": symbol,
                    "exit_date": day.date().isoformat(),
                    "exit_price": price,
                    "exit_reason": exit_reason,
                    "exit_cost": fee,
                })
                ledger.append({
                    "kind": "SELL",
                    "date": day.date().isoformat(),
                    "ticker": symbol,
                    "decision_date": position["decision_date"],
                    "entry_date": position["entry_date"],
                    "exit_reason": exit_reason,
                    "price": price,
                    "shares": position["shares"],
                    "notional": proceeds,
                    "fee": fee,
                    "liquidity_notional": 0.05 * traded_value,
                    "participation": participation,
                    "cash": cash,
                })
                del positions[symbol]

        open_nav = cash + sum(
            position["shares"]
            * _pit_bar(store, symbol, day, open_time)["open"]
            for symbol, position in positions.items()
        )
        for symbol, order in sorted(pending.pop(day, {}).items()):
            if symbol in positions:
                continue
            sector, _ = _pit_open_eligible(store, symbol, open_time, parameters)
            if not sector:
                rejected.append({"date": day.date().isoformat(), "ticker": symbol, "decision_date": order["decision_date"], "reason": "ORDER_REJECTED"})
                continue
            bar = _pit_bar(store, symbol, day, open_time)
            liquidity = 0.05 * _pit_trailing_liquidity(store, symbol, order["decision_day"], order["decision_as_of"], sessions)
            post_cost_weight_limit = (
                open_nav * order["weight"] / (1.0 + 0.0015 * 0.80)
            )
            desired = min(
                post_cost_weight_limit,
                liquidity,
                cash / 1.0015,
            )
            if desired <= 0:
                rejected.append({"date": day.date().isoformat(), "ticker": symbol, "decision_date": order["decision_date"], "reason": "ORDER_REJECTED"})
                continue
            fee, shares = desired * 0.0015, desired / bar["open"]
            cash -= desired + fee
            trade_notional += desired
            cost_notional += desired
            fees_paid += fee
            history = _residual_load_ohlcv(
                store,
                symbol,
                start=warmup_start.date().isoformat(),
                end=(day - pd.offsets.BDay(1)).date().isoformat(),
                as_of=open_time,
                bound_sessions=sessions,
            )
            expected_history = pd.DatetimeIndex(
                [item for item in sessions if item < day]
            )
            if len(expected_history.difference(history.index)):
                raise _residual_error("MISSING_CANDIDATE_HISTORY", symbol)
            history = history.reindex(expected_history)
            entry_factor = 1.0
            for action in _pit_actions(
                store,
                symbol,
                day,
                open_time,
                sessions,
            ):
                if action["action_type"] in {"SPLIT", "BONUS"}:
                    entry_factor *= action["factor"]
            stop = initial_stop(
                bar["open"],
                _residual_atr(
                    history, int(parameters.get("atr", 14))
                ) * entry_factor,
            )
            participation = desired / (liquidity / 0.05)
            positions[symbol] = {
                "decision_date": order["decision_date"],
                "entry_date": day.date().isoformat(),
                "entry_price": bar["open"],
                "cost_basis": bar["open"],
                "entry_cost": fee,
                "shares": shares,
                "stop": stop,
                "held_sessions": 0,
                "liquidity_notional": liquidity,
                "sector": sector,
            }
            buy_participations.append(participation)
            ledger.append({
                "kind": "BUY",
                "date": day.date().isoformat(),
                "ticker": symbol,
                "decision_date": order["decision_date"],
                "price": bar["open"],
                "shares": shares,
                "fee": fee,
                "notional": desired,
                "stop": stop,
                "sector": sector,
                "liquidity_notional": liquidity,
                "participation": participation,
                "cash": cash,
            })

        open_prices = {
            symbol: _pit_bar(store, symbol, day, open_time)["open"]
            for symbol in positions
        }
        open_exposure = _position_exposure(positions, open_prices, cash)

        for symbol, position in list(positions.items()):
            bar = _pit_bar(store, symbol, day, close_time)
            result = resolve_exit(
                {
                    "open": open_prices[symbol],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                },
                stop=position["stop"],
                rank_exit=False,
                held_sessions=0,
                forced_exit=False,
            )
            if result is not None and result[0] == "stop":
                proceeds = position["shares"] * result[1]
                fee = proceeds * 0.0015
                cash += proceeds - fee
                trade_notional += proceeds
                cost_notional += proceeds
                fees_paid += fee
                traded_value = _pit_trailing_traded_value(
                    store,
                    symbol,
                    day,
                    close_time,
                    sessions,
                    include_through_day=False,
                )
                participation = proceeds / traded_value
                sell_participations.append(participation)
                trades.append({**position, "ticker": symbol, "exit_date": day.date().isoformat(), "exit_price": result[1], "exit_reason": "intraday_stop", "exit_cost": fee})
                ledger.append({
                    "kind": "SELL",
                    "date": day.date().isoformat(),
                    "ticker": symbol,
                    "decision_date": position["decision_date"],
                    "entry_date": position["entry_date"],
                    "exit_reason": "intraday_stop",
                    "price": result[1],
                    "shares": position["shares"],
                    "notional": proceeds,
                    "fee": fee,
                    "liquidity_notional": 0.05 * traded_value,
                    "participation": participation,
                    "cash": cash,
                })
                del positions[symbol]

        close_prices = {
            symbol: _pit_bar(store, symbol, day, close_time)["close"]
            for symbol in positions
        }
        close_exposure = _position_exposure(positions, close_prices, cash)
        close_nav = close_exposure["nav"]
        for position in positions.values():
            position["held_sessions"] += 1
        values = close_exposure["position_values"]
        daily.append({
            "date": day,
            "starting_cash": starting_cash,
            "open_nav": open_nav,
            "post_trade_open_nav": open_exposure["nav"],
            "open_position_values": open_exposure["position_values"],
            "open_gross_exposure": open_exposure["gross"],
            "open_max_security": open_exposure["max_security"],
            "open_max_sector": open_exposure["max_sector"],
            "closing_cash": cash,
            "nav": close_nav,
            "position_values": values,
            "gross_exposure": close_exposure["gross"],
            "max_security": close_exposure["max_security"],
            "max_sector": close_exposure["max_sector"],
        })

        if day not in decision_days:
            continue
        universe = store.eligible_universe(close_time)
        close_history, sectors = {}, {}
        for symbol in universe:
            sector, eligible = _pit_open_eligible(store, symbol, close_time, parameters)
            if not eligible:
                continue
            frame = _residual_load_ohlcv(
                store,
                symbol,
                start=warmup_start.date().isoformat(),
                end=day.date().isoformat(),
                as_of=close_time,
                bound_sessions=sessions,
            )
            expected = pd.DatetimeIndex([item for item in sessions if item <= day])
            if len(expected.difference(frame.index)):
                raise _residual_error("MISSING_CANDIDATE_HISTORY", symbol)
            frame = frame.reindex(expected)
            sectors[symbol], close_history[symbol] = sector, frame["Close"]
        closes = pd.DataFrame(close_history)
        if closes.empty:
            raise _residual_error("MISSING_CANDIDATE_HISTORY")
        scores = compute_scores(closes, benchmark.reindex(closes.index), long_lag=long_lag, skip=skip)
        returns = closes.pct_change().dropna()
        correlation_lookback = int(parameters.get("correlation_lookback", 63))
        selected = select_candidates(scores, returns, limit=int(parameters.get("selection_limit", 10)), lookback=correlation_lookback, max_correlation=float(parameters.get("max_correlation", 0.80)))
        weights = allocate_weights(selected, returns, sectors, {symbol: 1.0 for symbol in selected}, gross_cap=0.80, security_cap=0.10, sector_cap=0.30, lookback=int(parameters.get("volatility_lookback", 63)))
        selected_correlation = _selected_pairwise_correlation(
            returns,
            selected,
            lookback=correlation_lookback,
        )
        selected_correlations.append(selected_correlation)
        targets = set(weights)
        decision = {
            "decision_date": day.date().isoformat(),
            "selected": selected,
            "weights": weights,
            "correlation_lookback": correlation_lookback,
            "max_pairwise_correlation": selected_correlation,
            "retained_holding_ages": {
                symbol: positions[symbol]["held_sessions"]
                for symbol in positions
                if symbol in weights
            },
        }
        decisions.append(decision)
        if index + 1 >= len(sessions):
            for symbol in weights:
                rejected.append({"date": day.date().isoformat(), "ticker": symbol, "decision_date": day.date().isoformat(), "reason": "NO_NEXT_SESSION"})
        else:
            next_day = sessions[index + 1]
            pending[next_day] = {symbol: {"weight": weight, "decision_date": day.date().isoformat(), "decision_day": day, "decision_as_of": close_time} for symbol, weight in weights.items() if symbol not in positions}

    nav_all = pd.Series({row["date"]: row["nav"] for row in daily}).sort_index()
    benchmark_returns_all = benchmark.pct_change()
    scored_index = nav_all.index[nav_all.index >= scored_start]
    returns = nav_all.pct_change().reindex(scored_index).dropna()
    benchmark_returns = benchmark_returns_all.reindex(returns.index)
    overall_policy = {"min_observations": 504, "bootstrap_samples": max(100, int(statistical_policy.get("bootstrap_samples", 2000))), "min_probability_positive": 0.95, "min_deflated_sharpe_probability": 0.95, "max_drawdown": 0.15, "n_trials": n_trials}
    overall = evaluate_outperformance(returns, benchmark_returns, policy=overall_policy)
    regime_result = _pit_regimes(returns, benchmark_returns, classify_benchmark_regimes(benchmark).reindex(returns.index), overall_policy)
    failed = sorted(set(
        overall["failed_gates"]
        + [
            f"regime:{name}"
            for name, result in regime_result["regimes"].items()
            if not result["passed"]
        ]
    ))
    annual_return = float((1.0 + returns).prod() ** (252 / len(returns)) - 1.0) if len(returns) else 0.0
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 and returns.std(ddof=1) else 0.0
    final_values = daily[-1]["position_values"] if daily else {}
    final_positions = {
        symbol: {
            **position,
            "mark_price": (
                final_values[symbol] / position["shares"]
                if position["shares"]
                else 0.0
            ),
            "notional": final_values[symbol],
        }
        for symbol, position in positions.items()
    }
    max_open_gross = max(
        (row["open_gross_exposure"] for row in daily), default=0.0
    )
    max_open_security = max(
        (row["open_max_security"] for row in daily), default=0.0
    )
    max_open_sector = max(
        (row["open_max_sector"] for row in daily), default=0.0
    )
    max_close_gross = max(
        (row["gross_exposure"] for row in daily), default=0.0
    )
    max_close_security = max(
        (row["max_security"] for row in daily), default=0.0
    )
    max_close_sector = max(
        (row["max_sector"] for row in daily), default=0.0
    )
    exposure = {
        "daily": daily,
        "max_open_gross": max_open_gross,
        "max_open_security": max_open_security,
        "max_open_sector": max_open_sector,
        "max_close_gross": max_close_gross,
        "max_close_security": max_close_security,
        "max_close_sector": max_close_sector,
        "max_gross": max(max_open_gross, max_close_gross),
        "max_security": max(max_open_security, max_close_security),
        "max_sector": max(max_open_sector, max_close_sector),
        "max_correlation": max(selected_correlations or [0.0]),
        "max_buy_participation": max(buy_participations or [0.0]),
        "max_sell_participation": max(sell_participations or [0.0]),
        "max_participation": max(
            buy_participations + sell_participations or [0.0]
        ),
    }
    return {
        "assumptions": {
            "fill_cost_bps": 15,
            "commission": 0,
            "max_hold_sessions": 20,
            "liquidity_participation": 0.05,
        },
        "source_hashes": source_hashes,
        "reproducibility_inputs": {
            "protocol": protocol,
            "benchmark_tri": benchmark,
            "n_trials": n_trials,
        },
        "n_trials": n_trials,
        "decisions": decisions,
        "trades": trades,
        "ledger": ledger,
        "rejected_orders": rejected,
        "portfolio": {
            "initial_cash": capital,
            "nav": nav_all.reindex(scored_index),
            "returns": returns,
            "cash": cash,
            "final_nav": float(nav_all.iloc[-1]) if len(nav_all) else cash,
            "open_positions": final_positions,
        },
        "benchmark_returns": benchmark_returns,
        "costs": {"notional": cost_notional, "total": fees_paid},
        "turnover": trade_notional / capital,
        "exposure": exposure,
        "coverage": {
            "sessions": len(sessions),
            "scored_sessions": len(returns),
        },
        "metrics": {
            "annualized_return": annual_return,
            "sharpe": sharpe,
        },
        "overall": overall,
        "regimes": regime_result,
        "failed_gates": failed,
    }


def run_residual_momentum_evaluation(
    store: ReliabilityStore,
    *,
    protocol: dict,
    benchmark_tri: pd.Series,
    preflight,
    registry: ExperimentRegistry,
    effective_n_trials: int,
) -> dict:
    """Verify two identical read-only simulations before returning a verdict."""
    if not isinstance(registry, ExperimentRegistry):
        raise _residual_error("INVALID_REGISTRY")
    token = None
    if protocol.get("experiment_id") in _CORPORATE_ACTION_REVIEW_EXPERIMENTS:
        manifest_payload = getattr(preflight, "manifest_payload", None)
        corporate = (
            manifest_payload.get("corporate_action_review")
            if isinstance(manifest_payload, dict)
            else None
        )
        if not isinstance(corporate, dict):
            raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR")
        try:
            binding = load_reviewed_factor_overrides(
                corporate["audit_path"],
                expected_sha256=corporate["audit_sha256"],
                packet_dir=corporate["packet_dir"],
                policy_path=corporate["policy_path"],
                baseline_report_path=corporate["baseline_path"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _residual_error("MISSING_CORPORATE_ACTION_FACTOR") from exc
        token = _ACTIVE_REVIEWED_FACTOR_OVERRIDES.set(binding)
    try:
        return _run_residual_momentum_evaluation_bound(
            store,
            protocol=protocol,
            benchmark_tri=benchmark_tri,
            preflight=preflight,
            registry=registry,
            effective_n_trials=effective_n_trials,
        )
    finally:
        if token is not None:
            _ACTIVE_REVIEWED_FACTOR_OVERRIDES.reset(token)


def _run_residual_momentum_evaluation_bound(
    store: ReliabilityStore,
    *,
    protocol: dict,
    benchmark_tri: pd.Series,
    preflight,
    registry: ExperimentRegistry,
    effective_n_trials: int,
) -> dict:
    preflight_evidence = _preflight_evidence(store, preflight, protocol)
    _, statistical_policy, _, _ = _residual_protocol(protocol)
    trial_floor = int(statistical_policy.get("n_trials_floor", 7))
    if (
        isinstance(effective_n_trials, bool)
        or not isinstance(effective_n_trials, int)
        or effective_n_trials < trial_floor
    ):
        raise _residual_error("INVALID_EFFECTIVE_N_TRIALS")
    n_trials = effective_n_trials
    input_manifest = _input_manifest(
        store,
        protocol=protocol,
        benchmark_tri=benchmark_tri,
        preflight_evidence=preflight_evidence,
        registry=registry,
        n_trials=n_trials,
    )
    input_manifest_sha256 = sha256_json(input_manifest)

    first_core = _run_residual_momentum_once(
        store,
        protocol=protocol,
        benchmark_tri=benchmark_tri,
        calendar_sessions=preflight_evidence["calendar_sessions"],
        calendar_closures=preflight_evidence["calendar_closures"],
        n_trials=n_trials,
        source_hashes=_simulation_source_hashes(preflight_evidence),
    )
    second_preflight_evidence = _preflight_evidence(
        store,
        preflight,
        protocol,
    )
    second_input_manifest = _input_manifest(
        store,
        protocol=protocol,
        benchmark_tri=benchmark_tri,
        preflight_evidence=second_preflight_evidence,
        registry=registry,
        n_trials=n_trials,
    )
    second_core = _run_residual_momentum_once(
        store,
        protocol=protocol,
        benchmark_tri=benchmark_tri,
        calendar_sessions=second_preflight_evidence[
            "calendar_sessions"
        ],
        calendar_closures=second_preflight_evidence[
            "calendar_closures"
        ],
        n_trials=n_trials,
        source_hashes=_simulation_source_hashes(
            second_preflight_evidence
        ),
    )
    final_preflight_evidence = _preflight_evidence(
        store,
        preflight,
        protocol,
    )
    final_input_manifest = _input_manifest(
        store,
        protocol=protocol,
        benchmark_tri=benchmark_tri,
        preflight_evidence=final_preflight_evidence,
        registry=registry,
        n_trials=n_trials,
    )
    first_bytes = _canonical_report_core_bytes(first_core)
    second_bytes = _canonical_report_core_bytes(second_core)
    first_hash = _sha256_bytes(first_bytes)
    second_hash = _sha256_bytes(second_bytes)
    reproducibility_verified = (
        input_manifest == second_input_manifest == final_input_manifest
        and first_bytes == second_bytes
    )
    verification = {
        **preflight_evidence["verification"],
        "order_queue_verified": not bool(first_core["rejected_orders"]),
        "reproducibility_verified": reproducibility_verified,
    }
    failed = sorted(set(
        first_core["failed_gates"]
        + _realized_gate_failures(first_core["exposure"], verification)
    ))
    report = {
        **first_core,
        "verdict": "ACCEPTED" if not failed else "REJECTED",
        "release_approved": False,
        "verification": verification,
        "reproducibility": {
            "verified": reproducibility_verified,
            "input_manifest": input_manifest,
            "input_manifest_sha256": input_manifest_sha256,
            "first_report_core_sha256": first_hash,
            "second_report_core_sha256": second_hash,
        },
        "report_core_sha256": first_hash,
        "failed_gates": failed,
    }
    return report
