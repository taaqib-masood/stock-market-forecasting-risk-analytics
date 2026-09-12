"""Normalize retained NSE report files into the reliability bundle contract."""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


def _key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path}: CSV has no header")
        rows = []
        for raw in reader:
            rows.append({_key(name): (value or "").strip() for name, value in raw.items()})
        return rows


def _value(row: dict[str, str], aliases: Iterable[str], label: str, required: bool = True) -> str:
    for alias in aliases:
        key = _key(alias)
        if key in row and row[key] != "":
            return row[key]
    if required:
        raise ValueError(f"missing required columns/value for {label}; accepted aliases: {', '.join(aliases)}")
    return ""


def _date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"unsupported date format: {value}") from exc


def _available(value: str | datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if len(text) == 10:
            text += "T00:00:00+00:00"
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _float(value: str) -> float | None:
    text = value.replace(",", "").strip()
    if text in ("", "-", "NA", "N/A", "NULL"):
        return None
    return float(text)


def _security_symbols(path: str | Path) -> set[str]:
    symbols = set()
    for row in _read_csv(path):
        symbol = _value(row, ("TckrSymb", "SYMBOL", "Ticker Symbol", "SYMB"), "symbol")
        series = _value(row, ("SctySrs", "SERIES", "Series"), "series", required=False)
        if series and series.upper() != "EQ":
            continue
        eligibility = _value(row, ("ElgbltyNrmlMkt",), "normal-market eligibility", required=False)
        if _key("ElgbltyNrmlMkt") in row and eligibility != "1":
            continue
        deleted = _value(row, ("DelFlg",), "delete flag", required=False)
        if deleted.upper() == "Y":
            continue
        isin = _value(row, ("ISIN",), "ISIN", required=False).upper()
        # Corporate equities use INE ISINs. INF identifies mutual-fund/ETF units,
        # which require holdings-based halal screening and a separate universe.
        if isin and (not isin.startswith("INE") or len(isin) != 12 or isin[7:9] != "01"):
            continue
        instrument_name = _value(row, ("FinInstrmNm",), "instrument name", required=False)
        if re.search(r"\bNCD\b|\bDEBENTURE", instrument_name.upper()):
            continue
        symbols.add(symbol.upper())
    return symbols


def normalize_membership_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build bitemporal open/close membership revisions from dated security snapshots."""
    ordered = sorted(snapshots, key=lambda item: _date(item["snapshot_date"]))
    active: dict[str, dict[str, str]] = {}
    output: list[dict[str, Any]] = []
    for item in ordered:
        snapshot_date = _date(item["snapshot_date"])
        available_at = _available(item["available_at"])
        current = _security_symbols(item["path"])
        for symbol in sorted(set(active) - current):
            opened = active.pop(symbol)
            output.append({
                "symbol": symbol,
                "valid_from": opened["valid_from"],
                "valid_to": snapshot_date,
                "available_at": available_at,
            })
        for symbol in sorted(current - set(active)):
            opened = {
                "symbol": symbol,
                "valid_from": snapshot_date,
                "available_at": available_at,
            }
            active[symbol] = opened
            output.append(dict(opened))
    return output


def normalize_bhavcopy(path: str | Path, *, available_at: str | datetime) -> list[dict[str, Any]]:
    output = []
    for row in _read_csv(path):
        series = _value(row, ("SctySrs", "SERIES", "Series"), "series", required=False)
        if series and series.upper() != "EQ":
            continue
        output.append({
            "symbol": _value(row, ("TckrSymb", "SYMBOL", "Ticker Symbol"), "symbol").upper(),
            "session_date": _date(_value(row, ("TradDt", "TIMESTAMP", "DATE1", "Date"), "trade date")),
            "open": float(_value(row, ("OpnPric", "OPEN", "Open Price"), "open")),
            "high": float(_value(row, ("HghPric", "HIGH", "High Price"), "high")),
            "low": float(_value(row, ("LwPric", "LOW", "Low Price"), "low")),
            "close": float(_value(row, ("ClsPric", "CLOSE", "Close Price"), "close")),
            "volume": float(_value(row, ("TtlTradgVol", "TOTTRDQTY", "VOLUME"), "volume")),
            "available_at": _available(available_at),
        })
    return output


def normalize_bhavcopy_exclusions(path: str | Path) -> list[dict[str, str]]:
    """Retain the series reason for rows deliberately excluded from EQ bars."""
    output = []
    for row in _read_csv(path):
        series = _value(row, ("SctySrs", "SERIES", "Series"), "series", required=False)
        if not series or series.upper() == "EQ":
            continue
        output.append({
            "symbol": _value(row, ("TckrSymb", "SYMBOL", "Ticker Symbol"), "symbol").upper(),
            "series": series.upper(),
            "session_date": _date(_value(
                row, ("TradDt", "TIMESTAMP", "DATE1", "Date"), "trade date"
            )),
        })
    return output


def _action_type(purpose: str) -> str:
    text = purpose.upper()
    for keyword, label in (
        ("BONUS", "BONUS"), ("SUB-DIVISION", "SPLIT"), ("SUB DIVISION", "SPLIT"),
        ("SPLIT", "SPLIT"), ("RIGHT", "RIGHTS"),
        ("DEMERGER", "DEMERGER"), ("MERGER", "MERGER"), ("DIVIDEND", "DIVIDEND"),
    ):
        if keyword in text:
            return label
    return "OTHER"


def normalize_corporate_actions(
    path: str | Path, *, available_at: str | datetime
) -> list[dict[str, Any]]:
    output = []
    for row in _read_csv(path):
        purpose = _value(row, ("PURPOSE",), "purpose")
        output.append({
            "symbol": _value(row, ("SYMBOL", "TckrSymb"), "symbol").upper(),
            "action_type": _action_type(purpose),
            "ex_date": _date(_value(row, ("EX-DATE", "EX DATE", "ExDt"), "ex date")),
            "available_at": _available(available_at),
            "payload": {
                "purpose": purpose,
                "record_date": _value(row, ("RECORD DATE", "RecordDt"), "record date", required=False),
            },
        })
    return output


def normalize_corporate_actions_snapshot(
    path: str | Path, *, available_at: str | datetime
) -> list[dict[str, Any]]:
    """Normalize a retained NSE API snapshot without inventing historical visibility."""
    return normalize_corporate_actions_snapshot_bytes(
        Path(path).read_bytes(),
        available_at=available_at,
    )


def normalize_corporate_actions_snapshot_bytes(
    content: bytes, *, available_at: str | datetime
) -> list[dict[str, Any]]:
    """Normalize exactly the retained snapshot bytes already verified by a caller."""
    try:
        payload = json.loads(content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("corporate action snapshot is invalid JSON") from error
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError("corporate action snapshot must be a JSON array of objects")
    snapshot_time = _available(available_at)
    output = []
    for raw in payload:
        row = {_key(str(name)): "" if value is None else str(value).strip()
               for name, value in raw.items()}
        series = _value(row, ("series", "SctySrs"), "series", required=False)
        if series and series.upper() != "EQ":
            continue
        purpose = _value(row, ("subject", "purpose"), "purpose")
        broadcast = _value(row, ("caBroadcastDate",), "broadcast date", required=False)
        known_at = _nse_timestamp(broadcast) if broadcast else snapshot_time
        output.append({
            "symbol": _value(row, ("symbol", "TckrSymb"), "symbol").upper(),
            "action_type": _action_type(purpose),
            "ex_date": _date(_value(row, ("exDate", "EX-DATE"), "ex date")),
            "available_at": known_at,
            "payload": {
                "purpose": purpose,
                "record_date": _value(row, ("recDate", "RECORD DATE"),
                                      "record date", required=False),
                "face_value": _float(_value(
                    row, ("faceVal", "FACE VALUE"), "face value", required=False
                )),
                "availability_source": "exchange_broadcast" if broadcast else "snapshot_retrieval",
            },
        })
    return output


def _date_tokens(value: str) -> set[str]:
    day = datetime.strptime(value, "%Y-%m-%d")
    return {
        day.strftime("%d-%b-%Y").upper(),
        day.strftime("%d-%b-%y").upper(),
        day.strftime("%d-%m-%Y"),
        day.strftime("%d/%m/%Y"),
        day.strftime("%B %d, %Y").upper(),
        f"{day.strftime('%B').upper()} {day.day}, {day.year}",
    }


def _economic_signature(
    action_type: str,
    text: str,
    face_value: float | None = None,
) -> tuple[float, ...] | None:
    upper = text.upper().replace(",", "")
    if action_type == "DIVIDEND":
        values = re.findall(
            r"DIVIDEND.{0,50}?(?:RS|RE)\.?[^\d]{0,6}(\d+(?:\.\d+)?)",
            upper,
        )
        if not values:
            values = re.findall(r"DIVIDEND\s+OF\s+(\d+(?:\.\d+)?)\s+PER", upper)
        if not values and face_value:
            percentages = re.findall(r"DIVIDEND.{0,50}?(\d+(?:\.\d+)?)\s*%", upper)
            values = [str(float(value) * face_value / 100.0) for value in percentages]
        return tuple(float(value) for value in values) if values else None
    if action_type in {"BONUS", "RIGHTS"}:
        match = re.search(rf"{action_type[:-1] if action_type == 'RIGHTS' else action_type}[^\d]*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", upper)
        return tuple(map(float, match.groups())) if match else None
    if action_type == "SPLIT":
        match = re.search(
            r"FROM\s+(?:RS|RE)\.?\s*(\d+(?:\.\d+)?).*?TO\s+(?:RS|RE)\.?\s*(\d+(?:\.\d+)?)",
            upper,
        )
        return tuple(map(float, match.groups())) if match else None
    return None


def reconcile_corporate_action_announcements(
    actions_path: str | Path,
    announcements_path: str | Path | list[str | Path],
    *,
    available_at: str | datetime,
) -> list[dict[str, Any]]:
    """Attach exchange broadcast time only to uniquely matching action announcements."""
    paths = announcements_path if isinstance(announcements_path, list) else [announcements_path]
    return reconcile_corporate_action_announcements_bytes(
        Path(actions_path).read_bytes(),
        [Path(value).read_bytes() for value in paths],
        available_at=available_at,
    )


def reconcile_corporate_action_announcements_bytes(
    actions_content: bytes,
    announcements_content: list[bytes],
    *,
    available_at: str | datetime,
) -> list[dict[str, Any]]:
    """Reconcile only bytes already read and integrity-checked by the caller."""
    actions = normalize_corporate_actions_snapshot_bytes(
        actions_content,
        available_at=available_at,
    )
    payload = []
    for content in announcements_content:
        try:
            rows = json.loads(content)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("corporate announcements are invalid JSON") from error
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("corporate announcements must be a JSON array of objects")
        payload.extend(rows)

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for raw in payload:
        symbol = str(raw.get("symbol", "")).strip().upper()
        broadcast = raw.get("an_dt") or raw.get("sort_date")
        if symbol and broadcast:
            by_symbol.setdefault(symbol, []).append(raw)

    for action in actions:
        purpose = action["payload"]["purpose"]
        action_type = action["action_type"]
        relevant_dates = {action["ex_date"]}
        record_date = action["payload"].get("record_date")
        if record_date and record_date != "-":
            relevant_dates.add(_date(record_date))
        tokens = set().union(*(_date_tokens(value) for value in relevant_dates))
        matches: list[tuple[str, bool]] = []
        face_value = action["payload"].get("face_value")
        action_signature = _economic_signature(action_type, purpose, face_value)
        for candidate in by_symbol.get(action["symbol"], []):
            text = " ".join(str(candidate.get(key, "")) for key in ("desc", "subject", "attchmntText"))
            if _action_type(text) != action_type:
                continue
            upper = text.upper()
            date_match = any(token in upper for token in tokens)
            candidate_signature = _economic_signature(action_type, text, face_value)
            economic_match = action_signature is not None and candidate_signature == action_signature
            if not date_match and not economic_match:
                continue
            broadcast = _nse_timestamp(str(candidate.get("an_dt") or candidate.get("sort_date")))
            if broadcast[:10] <= action["ex_date"]:
                matches.append((broadcast, economic_match))
        economic_matches = sorted({broadcast for broadcast, exact in matches if exact})
        date_matches = sorted({broadcast for broadcast, _exact in matches})
        if economic_matches:
            latest_announcement_day = economic_matches[-1][:10]
            action["available_at"] = min(
                value for value in economic_matches if value[:10] == latest_announcement_day
            )
            action["payload"]["availability_source"] = "matched_announcement"
        elif len(date_matches) == 1:
            action["available_at"] = date_matches[0]
            action["payload"]["availability_source"] = "matched_announcement"
        elif matches:
            action["payload"]["availability_source"] = "ambiguous_announcement"
    return actions


def normalize_financial_result_index(path: str | Path) -> list[dict[str, Any]]:
    """Normalize filing discovery metadata; XBRL facts are parsed separately."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("financial result index must contain an array of objects")
    output = []
    for raw in rows:
        row = {_key(str(name)): "" if value is None else str(value).strip()
               for name, value in raw.items()}
        filing = _value(row, ("broadCastDate", "filingDate"), "filing timestamp")
        xbrl = _value(row, ("xbrl",), "XBRL URL", required=False)
        if xbrl.endswith("/-") or not xbrl.startswith("https://nsearchives.nseindia.com/"):
            xbrl = ""
        output.append({
            "symbol": _value(row, ("symbol",), "symbol").upper(),
            "isin": _value(row, ("isin",), "ISIN", required=False).upper() or None,
            "period_start": _date(_value(row, ("fromDate",), "period start", required=False))
                            if _value(row, ("fromDate",), "period start", required=False) else None,
            "period_end": _date(_value(row, ("toDate",), "period end")),
            "available_at": _nse_timestamp(filing),
            "xbrl_url": xbrl or None,
            "consolidated": _value(row, ("consolidated",), "consolidated", required=False),
            "audited": _value(row, ("audited",), "audited", required=False),
        })
    return output


def _nse_timestamp(value: str) -> str:
    text = value.strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            continue
    return _available(text)


def normalize_business_classifications(path: str | Path) -> list[dict[str, Any]]:
    """Normalize independently reviewed point-in-time primary-business labels."""
    output = []
    for row in _read_csv(path):
        output.append({
            "symbol": _value(row, ("SYMBOL", "TckrSymb"), "symbol").upper(),
            "business_type": _value(
                row, ("BUSINESS_TYPE", "Business Type"), "business type"
            ).upper(),
            "effective_from": _date(_value(
                row, ("EFFECTIVE_FROM", "Effective From"), "effective from"
            )),
            "available_at": _available(_value(
                row, ("AVAILABLE_AT", "Available At"), "available at"
            )),
            "methodology_version": _value(
                row, ("METHODOLOGY_VERSION", "Methodology Version"), "methodology version"
            ),
            "reason": _value(row, ("REASON", "Reason"), "reason"),
        })
    return output


def normalize_financials(path: str | Path) -> list[dict[str, Any]]:
    """Normalize filing-derived rows; filing date is the earliest visibility timestamp."""
    source = Path(path)
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise ValueError("normalized financial JSON must be an array of objects")
        required = {"symbol", "period_end", "available_at", "debt_to_assets",
                    "interest_income_ratio"}
        output = []
        for row in payload:
            missing = required - set(row)
            if missing:
                raise ValueError(f"normalized financial JSON missing: {', '.join(sorted(missing))}")
            output.append({
                "symbol": str(row["symbol"]).upper(),
                "period_end": _date(row["period_end"]),
                "effective_from": _date(row.get("effective_from") or row["available_at"]),
                "available_at": _available(row["available_at"]),
                "debt_to_assets": float(row["debt_to_assets"])
                if row["debt_to_assets"] is not None else None,
                "interest_income_ratio": float(row["interest_income_ratio"])
                if row["interest_income_ratio"] is not None else None,
                "business_type": str(row["business_type"]).strip().upper()
                if row.get("business_type") else None,
                "payload": row.get("payload", {}),
            })
        return output
    output = []
    for row in _read_csv(path):
        filing_date = _date(_value(row, ("FILING_DATE", "Filing Date", "AVAILABLE_AT"), "filing date"))
        debt = _float(_value(row, ("TOTAL_DEBT", "Total Debt"), "total debt", required=False))
        assets = _float(_value(row, ("TOTAL_ASSETS", "Total Assets"), "total assets", required=False))
        interest = _float(_value(row, ("INTEREST_INCOME", "Interest Income"), "interest income", required=False))
        revenue = _float(_value(row, ("TOTAL_REVENUE", "Total Revenue"), "total revenue", required=False))
        output.append({
            "symbol": _value(row, ("SYMBOL", "TckrSymb"), "symbol").upper(),
            "period_end": _date(_value(row, ("PERIOD_END", "Period End"), "period end")),
            "effective_from": _date(_value(
                row, ("EFFECTIVE_FROM",), "effective from", required=False
            ) or filing_date),
            "available_at": _available(filing_date),
            "debt_to_assets": debt / assets if debt is not None and assets not in (None, 0) else None,
            "interest_income_ratio": (
                abs(interest) / revenue if interest is not None and revenue not in (None, 0) else None
            ),
            "business_type": (
                _value(row, ("BUSINESS_TYPE", "Business Type"), "business type", required=False)
                or None
            ),
            "payload": {
                "total_debt": debt, "total_assets": assets,
                "interest_income": interest, "total_revenue": revenue,
            },
        })
    return output
