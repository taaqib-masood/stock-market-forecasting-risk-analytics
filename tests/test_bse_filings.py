import json
from datetime import date

from src.reliability.bse_filings import (
    bse_announcements_request,
    normalize_bse_financial_announcements,
)


def test_bse_request_is_bounded_and_symbol_specific():
    request = bse_announcements_request("ABBOTINDIA", "500488", date(2024, 1, 1), date(2024, 7, 5))

    assert request.endpoint.endswith("/api/AnnSubCategoryGetData/w")
    assert request.params["strscrip"] == "500488"
    assert request.params["strPrevDate"] == "20240101"
    assert request.filename == "bse-announcements-ABBOTINDIA-20240101-20240705.json"


def test_bse_normalizer_keeps_results_and_rejects_board_meeting_noise(tmp_path):
    path = tmp_path / "bse.json"
    path.write_text(json.dumps({"Table": [
        {"NEWSID": "result-id", "SCRIP_CD": 500488,
         "NEWSSUB": "Financial Results For The Quarter And Financial Year Ended March 31, 2024",
         "DT_TM": "2024-05-09T18:36:35.87", "ATTACHMENTNAME": "result.pdf",
         "CATEGORYNAME": "Result"},
        {"NEWSID": "meeting-id", "SCRIP_CD": 500488,
         "NEWSSUB": "Board Meeting Intimation for approving financial results",
         "DT_TM": "2024-04-29T15:24:56.377", "ATTACHMENTNAME": "meeting.pdf",
         "CATEGORYNAME": "Board Meeting"},
        {"NEWSID": "future", "SCRIP_CD": 500488, "NEWSSUB": "Financial Results",
         "DT_TM": "2024-07-10T10:00:00", "ATTACHMENTNAME": "future.pdf",
         "CATEGORYNAME": "Result"},
    ]}))

    rows = normalize_bse_financial_announcements(
        path, symbol="ABBOTINDIA", cutoff="2024-07-05T23:59:59Z"
    )

    assert len(rows) == 1
    assert rows[0]["available_at"] == "2024-05-09T13:06:35Z"
    assert rows[0]["attachment_url"].endswith("/result.pdf")
    assert rows[0]["news_id"] == "result-id"
