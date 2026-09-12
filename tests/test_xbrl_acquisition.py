import hashlib
import json

import pytest

from src.reliability.xbrl import XbrlAcquirer, XbrlError, parse_halal_financial_facts


XBRL = b'''<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:in="https://example.test/in">
  <context id="annual"><entity><identifier scheme="x">TCS</identifier></entity>
    <period><startDate>2023-04-01</startDate><endDate>2024-03-31</endDate></period></context>
  <in:Assets contextRef="annual" decimals="0">1000</in:Assets>
  <in:BorrowingsCurrent contextRef="annual">50</in:BorrowingsCurrent>
  <in:BorrowingsNoncurrent contextRef="annual">150</in:BorrowingsNoncurrent>
  <in:RevenueFromOperations contextRef="annual">800</in:RevenueFromOperations>
  <in:InterestIncome contextRef="annual">20</in:InterestIncome>
</xbrl>'''


class FakeResponse:
    def __init__(self, content, status_code=200, content_type="application/xml"):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": content_type}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_xbrl_acquirer_retains_valid_allowlisted_document(tmp_path):
    client = FakeClient([FakeResponse(XBRL)])
    result = XbrlAcquirer(tmp_path, client=client, retries=1).acquire(
        "https://nsearchives.nseindia.com/corporate/xbrl/TCS.xml"
    )

    assert result.status == "downloaded"
    assert result.sha256 == hashlib.sha256(XBRL).hexdigest()
    assert result.path.read_bytes() == XBRL
    assert json.loads((tmp_path / "source-catalogue.jsonl").read_text().splitlines()[-1])["status"] == "downloaded"


def test_xbrl_acquirer_retries_then_uses_immutable_cache(tmp_path):
    client = FakeClient([OSError("timeout"), FakeResponse(XBRL)])
    acquirer = XbrlAcquirer(tmp_path, client=client, retries=2, sleep=lambda _: None)
    url = "https://nsearchives.nseindia.com/corporate/xbrl/TCS.xml"

    assert acquirer.acquire(url).status == "downloaded"
    assert acquirer.acquire(url).status == "cached"
    assert client.calls == 2


@pytest.mark.parametrize("url, response", [
    ("https://evil.test/TCS.xml", FakeResponse(XBRL)),
    ("https://nsearchives.nseindia.com/corporate/xbrl/TCS.xml",
     FakeResponse(b"<html>blocked</html>", content_type="text/html")),
    ("https://nsearchives.nseindia.com/corporate/xbrl/TCS.xml", FakeResponse(b"not xml")),
])
def test_xbrl_acquirer_rejects_untrusted_or_invalid_documents(tmp_path, url, response):
    with pytest.raises(XbrlError):
        XbrlAcquirer(tmp_path, client=FakeClient([response]), retries=1).acquire(url)


def test_xbrl_parser_derives_halal_ratios_from_period_context(tmp_path):
    path = tmp_path / "TCS.xml"
    path.write_bytes(XBRL)

    row = parse_halal_financial_facts(
        path, symbol="TCS", period_end="2024-03-31", available_at="2024-04-20T10:00:00Z"
    )

    assert row["debt_to_assets"] == 0.2
    assert row["interest_income_ratio"] == 0.025
    assert row["payload"]["total_debt"] == 200.0


def test_xbrl_parser_fails_closed_when_interest_income_is_missing(tmp_path):
    path = tmp_path / "TCS.xml"
    path.write_bytes(XBRL.replace(b'<in:InterestIncome contextRef="annual">20</in:InterestIncome>', b''))

    row = parse_halal_financial_facts(
        path, symbol="TCS", period_end="2024-03-31", available_at="2024-04-20T10:00:00Z"
    )

    assert row["debt_to_assets"] == 0.2
    assert row["interest_income_ratio"] is None


def test_xbrl_parser_retains_ambiguous_interest_candidates_without_promoting_them(tmp_path):
    content = XBRL.replace(
        b'<in:InterestIncome contextRef="annual">20</in:InterestIncome>',
        b'<in:AdjustmentsForInterestIncome contextRef="annual">-20</in:AdjustmentsForInterestIncome>'
        b'<in:InterestReceivedClassifiedAsInvestingActivities contextRef="annual">18</in:InterestReceivedClassifiedAsInvestingActivities>',
    )
    path = tmp_path / "TCS.xml"
    path.write_bytes(content)

    row = parse_halal_financial_facts(
        path, symbol="TCS", period_end="2024-03-31", available_at="2024-04-20T10:00:00Z"
    )

    assert row["interest_income_ratio"] is None
    assert row["payload"]["interest_income_candidates"] == {
        "AdjustmentsForInterestIncome": [-20.0],
        "InterestReceivedClassifiedAsInvestingActivities": [18.0],
    }


def test_xbrl_parser_uses_longest_duration_and_instant_balance_context(tmp_path):
    content = b'''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:i="x">
      <context id="q"><period><startDate>2024-01-01</startDate><endDate>2024-03-31</endDate></period></context>
      <context id="fy"><period><startDate>2023-04-01</startDate><endDate>2024-03-31</endDate></period></context>
      <context id="at"><period><instant>2024-03-31</instant></period></context>
      <i:Assets contextRef="at">1000</i:Assets><i:Borrowings contextRef="at">200</i:Borrowings>
      <i:RevenueFromOperations contextRef="q">200</i:RevenueFromOperations>
      <i:RevenueFromOperations contextRef="fy">800</i:RevenueFromOperations>
      <i:InterestIncome contextRef="q">5</i:InterestIncome>
      <i:InterestIncome contextRef="fy">20</i:InterestIncome>
    </xbrl>'''
    path = tmp_path / "annual.xml"
    path.write_bytes(content)

    row = parse_halal_financial_facts(
        path, symbol="TCS", period_end="2024-03-31", available_at="2024-04-20T10:00:00Z"
    )

    assert row["payload"]["total_revenue"] == 800.0
    assert row["payload"]["interest_income"] == 20.0
    assert row["debt_to_assets"] == 0.2
