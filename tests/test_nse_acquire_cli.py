import json
from datetime import date

import pytest

from src.reliability.nse_acquire import build_specs, monthly_ranges, parse_date, run


def test_build_specs_switches_bhavcopy_format_at_udiff_cutover():
    specs = build_specs("bhavcopy", date(2024, 7, 5), date(2024, 7, 8), holidays=set())
    assert [spec.filename for spec in specs] == [
        "cm05JUL2024bhav.csv.zip",
        "BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip",
    ]


def test_build_specs_supports_template_override():
    specs = build_specs(
        "security_master",
        date(2024, 7, 8),
        date(2024, 7, 8),
        holidays=set(),
        template="https://mirror.test/{filename}",
    )
    assert specs[0].url == "https://mirror.test/NSE_CM_security_08072024.csv.gz"


def test_run_requires_bounded_range_and_positive_rate(tmp_path):
    with pytest.raises(ValueError, match="31 days"):
        run("bhavcopy", date(2024, 1, 1), date(2024, 3, 1), tmp_path, 1.0, set(), None, True)
    with pytest.raises(ValueError, match="rate"):
        run("bhavcopy", date(2024, 1, 1), date(2024, 1, 2), tmp_path, 0, set(), None, True)


def test_dry_run_returns_specs_without_downloading(tmp_path):
    result = run(
        "bhavcopy", date(2024, 7, 8), date(2024, 7, 8), tmp_path, 1.0, set(), None, True
    )
    assert result[0]["status"] == "planned"
    assert result[0]["session_date"] == "2024-07-08"
    assert list(tmp_path.iterdir()) == []


def test_parse_date_rejects_non_iso_date():
    with pytest.raises(ValueError):
        parse_date("08-07-2024")


def test_monthly_ranges_cover_history_without_exceeding_acquisition_bound():
    ranges = monthly_ranges(date(2019, 12, 20), date(2020, 2, 10))

    assert ranges == [
        (date(2019, 12, 20), date(2019, 12, 31)),
        (date(2020, 1, 1), date(2020, 1, 31)),
        (date(2020, 2, 1), date(2020, 2, 10)),
    ]
    assert all((end - start).days < 31 for start, end in ranges)
