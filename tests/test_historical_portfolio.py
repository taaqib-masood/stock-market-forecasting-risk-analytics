import pandas as pd

from tests.corporate_action_test_support import issue_reviewed_factor_chain
from src.reliability.historical_portfolio import (
    classify_benchmark_regimes,
    load_ohlcv,
    select_liquid_universe,
    run_static_universe_diagnostic,
    build_monthly_liquidity_universes,
    filter_trades_by_monthly_universe,
    filter_trades_by_regime,
)
from src.strategy import Strategy
from src.reliability.store import ReliabilityStore


def _verified_rights_binding(tmp_path):
    return issue_reviewed_factor_chain(tmp_path).capability


def test_load_ohlcv_reads_only_visible_point_in_time_bars(tmp_path):
    store = ReliabilityStore(tmp_path / "history.db")
    manifest = store.register_manifest("bhavcopy", b"one", "2020-01-02T18:00:00Z")
    store.put_bar("TCS", "2020-01-02", 100, 110, 90, 105, 1000,
                  "2020-01-02T18:00:00Z", manifest)
    future = store.register_manifest("bhavcopy", b"future", "2020-01-03T18:00:00Z")
    store.put_bar("TCS", "2020-01-03", 105, 115, 95, 110, 2000,
                  "2020-01-03T18:00:00Z", future)

    frame = load_ohlcv(
        store, "TCS", start="2020-01-01", end="2020-01-03",
        as_of="2020-01-03T17:59:59Z",
    )

    assert frame.index.strftime("%Y-%m-%d").tolist() == ["2020-01-02"]
    assert frame.columns.tolist() == ["Open", "High", "Low", "Close", "Volume"]
    assert frame.iloc[0]["Close"] == 105


def test_load_ohlcv_applies_only_actions_visible_as_of_query(tmp_path):
    store = ReliabilityStore(tmp_path / "prices.db")
    bars = store.register_manifest("bars", b"bars", "2024-01-03T18:00:00Z")
    action = store.register_manifest("actions", b"action", "2024-01-02T12:00:00Z")
    future = store.register_manifest("actions", b"future", "2024-02-01T12:00:00Z")
    store.put_bar("TCS", "2024-01-01", 98, 101, 97, 100, 1000,
                  "2024-01-01T18:00:00Z", bars)
    store.put_bar("TCS", "2024-01-02", 102, 104, 99, 100, 1200,
                  "2024-01-02T18:00:00Z", bars)
    store.put_bar("TCS", "2024-01-03", 51, 53, 50, 52, 2400,
                  "2024-01-03T18:00:00Z", bars)
    store.put_corporate_action(
        "TCS", "SPLIT", "2024-01-03",
        {"purpose": "Face Value Split From Rs 10 Per Share To Rs 5 Per Share"},
        "2024-01-02T12:00:00Z", action,
    )
    store.put_corporate_action(
        "TCS", "DEMERGER", "2024-01-03", {"purpose": "Demerger"},
        "2024-02-01T12:00:00Z", future,
    )

    frame = load_ohlcv(
        store, "TCS", start="2024-01-01", end="2024-01-03",
        as_of="2024-01-03T23:59:59Z",
    )

    assert list(frame["Close"]) == [50.0, 50.0, 52.0]


def test_load_ohlcv_applies_rights_factor_only_from_verified_review_binding(tmp_path):
    binding = _verified_rights_binding(tmp_path)
    store = ReliabilityStore(tmp_path / "prices.db")
    bars = store.register_manifest("bars", b"bars", "2024-01-03T18:00:00Z")
    actions = store.register_manifest("actions", b"actions", "2024-01-02T12:00:00Z")
    for day, close in (("2024-01-01", 100), ("2024-01-02", 100), ("2024-01-03", 52)):
        store.put_bar("TCS", day, close, close, close, close, 1000, f"{day}T18:00:00Z", bars)
    store.put_corporate_action(
        "TCS",
        "RIGHTS",
        "2024-01-03",
        {"purpose": "Rights 1:4 @ Premium Rs 10"},
        "2024-01-02T12:00:00Z",
        actions,
    )

    frame = load_ohlcv(
        store,
        "TCS",
        start="2024-01-01",
        end="2024-01-03",
        as_of="2024-01-03T23:59:59Z",
        reviewed_factor_overrides=binding,
    )

    assert frame.loc["2024-01-02", "Close"] == 75.0


def test_liquid_universe_selection_uses_only_data_through_cutoff(tmp_path):
    store = ReliabilityStore(tmp_path / "history.db")
    manifest = store.register_manifest("bhavcopy", b"bars", "2020-01-03T18:00:00Z")
    for symbol, volume in [("LIQUID", 1000), ("THIN", 10)]:
        for day in ("2020-01-01", "2020-01-02"):
            store.put_bar(symbol, day, 10, 10, 10, 10, volume, f"{day}T18:00:00Z", manifest)
    store.put_bar("FUTURE", "2020-01-03", 10, 10, 10, 10, 1_000_000,
                  "2020-01-03T18:00:00Z", manifest)

    result = select_liquid_universe(store, through="2020-01-02", limit=2, min_sessions=2)

    assert result == ["LIQUID", "THIN"]


def test_benchmark_regimes_are_lagged_one_session():
    index = pd.date_range("2020-01-01", periods=260, freq="B")
    close = pd.Series(range(100, 360), index=index, dtype=float)

    regimes = classify_benchmark_regimes(close)

    assert regimes.iloc[0] == "SIDEWAYS"
    assert regimes.iloc[199] == "SIDEWAYS"
    assert regimes.iloc[200] == "BULL"


class _NoSignal(Strategy):
    name = "none"

    def generate_signals(self, features):
        return pd.DataFrame({"score": 0.0, "signal": 0, "confidence": 0.0}, index=features.index)


def test_static_diagnostic_returns_benchmark_relative_failed_verdict(tmp_path):
    store = ReliabilityStore(tmp_path / "history.db")
    dates = pd.date_range("2019-01-01", periods=320, freq="B")
    rows = []
    for symbol, offset in [("STOCK", 0), ("NIFTYBEES", 10)]:
        for number, day in enumerate(dates):
            price = 100 + offset + number * 0.1
            rows.append({"symbol": symbol, "session_date": day.date().isoformat(),
                         "open": price, "high": price + 1, "low": price - 1,
                         "close": price, "volume": 1000,
                         "available_at": f"{day.date().isoformat()}T18:00:00Z"})
    manifest = store.register_manifest("bhavcopy", b"diagnostic", "2020-03-31T18:00:00Z")
    store.put_bars(rows, manifest)

    result = run_static_universe_diagnostic(
        store, ["STOCK"], start="2019-01-01", end="2020-03-31",
        test_start="2020-01-01", benchmark_symbol="NIFTYBEES",
        strategy=_NoSignal(), statistical_policy={"min_observations": 20,
                                                  "bootstrap_samples": 100},
    )

    assert result["completed_trades"] == 0
    assert result["overall"]["passed"] is False
    assert result["portfolio"]["returns"].index.min() >= pd.Timestamp("2020-01-01")


def test_monthly_liquidity_universe_uses_only_prior_sessions(tmp_path):
    store = ReliabilityStore(tmp_path / "history.db")
    dates = pd.date_range("2020-01-01", "2020-02-10", freq="B")
    rows = []
    for day in dates:
        for symbol, volume in [("OLD_LIQUID", 1000), ("FUTURE_SPIKE", 10)]:
            if symbol == "FUTURE_SPIKE" and day >= pd.Timestamp("2020-02-03"):
                volume = 1_000_000
            rows.append({"symbol": symbol, "session_date": day.date().isoformat(),
                         "open": 10, "high": 10, "low": 10, "close": 10,
                         "volume": volume, "available_at": f"{day.date().isoformat()}T18:00:00Z"})
    manifest = store.register_manifest("bhavcopy", b"monthly", "2020-02-10T18:00:00Z")
    store.put_bars(rows, manifest)

    universes = build_monthly_liquidity_universes(
        store, start="2020-02-01", end="2020-02-10", limit=1,
        lookback_sessions=20, min_sessions=10,
    )

    assert list(universes.values()) == [["OLD_LIQUID"]]


def test_trade_filter_uses_universe_effective_on_signal_date():
    trades = pd.DataFrame([
        {"ticker": "A", "signal_date": "2020-01-15"},
        {"ticker": "B", "signal_date": "2020-02-15"},
        {"ticker": "A", "signal_date": "2020-02-15"},
    ])
    universes = {"2020-01-02": ["A"], "2020-02-03": ["B"]}

    filtered = filter_trades_by_monthly_universe(trades, universes)

    assert filtered[["ticker", "signal_date"]].astype(str).values.tolist() == [
        ["A", "2020-01-15"], ["B", "2020-02-15"]
    ]


def test_trade_filter_uses_regime_known_on_signal_date():
    trades = pd.DataFrame([
        {"ticker": "A", "signal_date": "2020-01-02"},
        {"ticker": "B", "signal_date": "2020-01-03"},
    ])
    regimes = pd.Series(
        ["BULL", "SIDEWAYS"], index=pd.to_datetime(["2020-01-02", "2020-01-03"])
    )

    filtered = filter_trades_by_regime(trades, regimes, allowed={"BULL"})

    assert filtered["ticker"].tolist() == ["A"]
