"""Retained BSE announcement requests and point-in-time result metadata."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.reliability.nse_api_acquisition import ApiRequest


BSE_ROOT = "https://www.bseindia.com"
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api"


def bse_announcements_request(
    symbol: str, scrip_code: str, start: date, end: date
) -> ApiRequest:
    normalized = symbol.strip().upper()
    code = str(scrip_code).strip()
    if not normalized or not code.isdigit() or len(code) != 6:
        raise ValueError("BSE request requires a symbol and six-digit scrip code")
    if end < start or (end - start).days > 366:
        raise ValueError("BSE announcement request must span at most 367 days")
    return ApiRequest(
        kind="bse_financial_announcements",
        snapshot_date=end,
        endpoint=f"{BSE_API}/AnnSubCategoryGetData/w",
        params={
            "pageno": "1", "strCat": "-1", "subcategory": "-1",
            "strPrevDate": start.strftime("%Y%m%d"), "strToDate": end.strftime("%Y%m%d"),
            "strSearch": "P", "strscrip": code, "strType": "C",
        },
        filename=f"bse-announcements-{normalized}-{start:%Y%m%d}-{end:%Y%m%d}.json",
        bootstrap_url=f"{BSE_ROOT}/corporates/ann.html",
    )


def normalize_bse_financial_announcements(
    path: str | Path, *, symbol: str, cutoff: str
) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("Table", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("BSE announcement snapshot must contain a Table array")
    point = _dt(cutoff)
    output = []
    for row in rows:
        subject = str(row.get("NEWSSUB") or "").strip()
        category = str(row.get("CATEGORYNAME") or "").strip().lower()
        lowered = subject.lower()
        is_result = category == "result" or (
            "board meeting outcome" in lowered and "financial results" in lowered
        )
        if not is_result:
            continue
        available_at = _bse_time(str(row.get("DT_TM") or ""))
        if _dt(available_at) > point:
            continue
        attachment = str(row.get("ATTACHMENTNAME") or "").strip()
        news_id = str(row.get("NEWSID") or "").strip()
        scrip_code = str(row.get("SCRIP_CD") or "").strip()
        output.append({
            "symbol": symbol.upper(), "scrip_code": scrip_code, "news_id": news_id,
            "subject": subject, "available_at": available_at,
            "attachment_url": f"{BSE_ROOT}/xml-data/corpfiling/AttachHis/{attachment}"
                              if attachment else None,
            "xbrl_render_url": (f"{BSE_ROOT}/Msource/90D/CorpXbrlGen.aspx?"
                                f"Bsenewid={news_id}&Scripcode={scrip_code}")
                               if news_id and scrip_code else None,
        })
    return sorted(output, key=lambda row: row["available_at"])


def _bse_time(value: str) -> str:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid BSE filing timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
