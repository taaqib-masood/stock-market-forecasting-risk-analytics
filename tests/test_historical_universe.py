import csv

from src.reliability.historical_universe import audit_tradable_universe


def _bhav(path, day, symbols):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "SYMBOL", "SERIES", "TIMESTAMP", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"
        ])
        writer.writeheader()
        for symbol in symbols:
            writer.writerow({"SYMBOL": symbol, "SERIES": "EQ", "TIMESTAMP": day,
                             "OPEN": 1, "HIGH": 1, "LOW": 1, "CLOSE": 1, "TOTTRDQTY": 1})


def test_historical_universe_reports_churn_without_current_survivorship_filter(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    _bhav(first, "01-JAN-2020", ["OLDCO", "KEEP"])
    _bhav(second, "02-JAN-2020", ["KEEP", "NEWCO"])

    result = audit_tradable_universe([first, second], current_symbols={"KEEP", "NEWCO"})

    assert result["sessions"] == 2
    assert result["unique_symbols"] == 3
    assert result["historical_not_current"] == ["OLDCO"]
    assert result["symbol_history"]["OLDCO"] == {
        "first_seen": "2020-01-01", "last_seen": "2020-01-01", "sessions": 1
    }
    assert result["symbol_history"]["KEEP"]["sessions"] == 2
