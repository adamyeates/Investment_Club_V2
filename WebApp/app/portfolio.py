"""Turn raw sheet rows into the JSON the website renders."""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Callable

from . import config

_NUM_STRIP = re.compile(r"[$,\s]")


def to_number(value: Any) -> float | None:
    """'$1,018.30' -> 1018.3, '(12.50)' -> -12.5, '' / '-' / '#N/A' -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = _NUM_STRIP.sub("", str(value)).replace("%", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    if text in ("", "-", "—"):
        return None
    try:
        n = float(text)
    except ValueError:
        return None
    return -n if negative else n


def to_percent(value: Any) -> float | None:
    """Percent cells arrive as fractions from the API/xlsx (-0.073) and as text from
    CSV ('-7.3%'). Always return percentage points (-7.3)."""
    if isinstance(value, str) and "%" in value:
        return to_number(value)
    n = to_number(value)
    return None if n is None else n * 100


def to_iso_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (int, float)):  # Sheets serial date
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(value))).isoformat()
    text = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%Y-%m-%d %H:%M:%S", "%b %d, %Y", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _header_index(header: list, test: Callable[[str], bool]) -> int:
    for i, h in enumerate(header):
        if test(str(h or "").strip().lower()):
            return i
    return -1


def _cell(row: list, i: int) -> Any:
    return row[i] if 0 <= i < len(row) else None


def parse_holdings(rows: list[list]) -> list[dict]:
    """Columns are matched by header name (Symbol, Name, Last Price $, Quantity,
    Price Paid $, YTD %, Value $, Sector) so they can be reordered in the sheet.
    Reading stops at the first row with no ticker: below the holdings the tab has a
    totals row and a small performance table we don't want treated as positions."""
    if not rows:
        return []
    header = rows[0]
    idx = {
        "sym": _header_index(header, lambda h: h in ("symbol", "ticker")),
        "name": _header_index(header, lambda h: h in ("name", "company")),
        "last": _header_index(header, lambda h: "last" in h or ("price" in h and "paid" not in h)),
        "qty": _header_index(header, lambda h: "quantity" in h or "shares" in h),
        "cost": _header_index(header, lambda h: "paid" in h or "cost" in h),
        "ytd": _header_index(header, lambda h: "ytd" in h),
        "value": _header_index(header, lambda h: h.startswith("value")),
        "sector": _header_index(header, lambda h: h == "sector"),
        "beta": _header_index(header, lambda h: h == "beta"),
    }
    missing = [k for k in ("sym", "last", "qty") if idx[k] < 0]
    if missing:
        raise ValueError(f"Portfolio tab is missing expected columns: {', '.join(missing)}")

    holdings = []
    for row in rows[1:]:
        sym = str(_cell(row, idx["sym"]) or "").strip()
        if not sym:
            break
        is_cash = sym.upper() in config.CASH_TICKERS
        shares = to_number(_cell(row, idx["qty"]))
        last = to_number(_cell(row, idx["last"]))
        cost = to_number(_cell(row, idx["cost"]))
        value = to_number(_cell(row, idx["value"]))
        if value is None and shares is not None and last is not None:
            value = shares * last
        ret = None
        gain = None
        if not is_cash and cost and shares is not None and last is not None:
            ret = (last - cost) / cost * 100
            gain = (last - cost) * shares
        holdings.append({
            "sym": sym,
            "name": str(_cell(row, idx["name"]) or "").strip(),
            "sector": str(_cell(row, idx["sector"]) or "").strip() or "Other",
            "shares": None if is_cash else shares,
            "cost": None if is_cash else cost,
            "last": None if is_cash else last,
            "value": value or 0.0,
            "gain": gain,
            "ret": ret,
            "ytd": None if is_cash else to_percent(_cell(row, idx["ytd"])),
            "beta": to_number(_cell(row, idx["beta"])),
            "cash": is_cash,
        })
    return holdings


def parse_transactions(rows: list[list]) -> list[dict]:
    """Transactions tab: Date, Ticker, Action, Quantity, Price, Value. Newest first."""
    if not rows:
        return []
    header = rows[0]
    idx = {
        "date": _header_index(header, lambda h: h == "date"),
        "sym": _header_index(header, lambda h: h in ("ticker", "symbol")),
        "action": _header_index(header, lambda h: h in ("action", "type", "side")),
        "qty": _header_index(header, lambda h: "quantity" in h or "shares" in h),
        "price": _header_index(header, lambda h: h == "price" or h.startswith("price")),
        "value": _header_index(header, lambda h: h.startswith("value") or h == "amount"),
    }
    if idx["date"] < 0 or idx["sym"] < 0:
        return []

    out = []
    for row in rows[1:]:
        sym = str(_cell(row, idx["sym"]) or "").strip()
        date = to_iso_date(_cell(row, idx["date"]))
        if not sym or not date:
            continue
        action = str(_cell(row, idx["action"]) or "").strip().upper()
        qty = to_number(_cell(row, idx["qty"]))
        price = to_number(_cell(row, idx["price"]))
        value = to_number(_cell(row, idx["value"]))
        if value is None and qty is not None and price is not None:
            value = qty * price
        out.append({
            "date": date,
            "sym": sym,
            "action": action,
            # the sheet records some sells as negative quantities; show size only
            "shares": abs(qty) if qty is not None else None,
            "price": price,
            "amount": abs(value) if value is not None else None,
        })
    out.sort(key=lambda t: t["date"], reverse=True)  # stable: same-day order kept
    return out


def summarize(holdings: list[dict]) -> dict:
    total = sum(h["value"] for h in holdings)
    invested = [h for h in holdings if h["gain"] is not None]
    gain = sum(h["gain"] for h in invested)
    basis = sum(h["cost"] * h["shares"] for h in invested)
    for h in holdings:
        h["weight"] = h["value"] / total * 100 if total else 0.0

    sectors: dict[str, float] = {}
    for h in holdings:
        sectors[h["sector"]] = sectors.get(h["sector"], 0.0) + h["value"]
    allocation = sorted(
        ({"sector": s, "value": v, "pct": v / total * 100 if total else 0.0} for s, v in sectors.items()),
        key=lambda a: a["value"], reverse=True,
    )

    beta_rows = [h for h in holdings if h["beta"] is not None]
    beta = sum(h["weight"] / 100 * h["beta"] for h in beta_rows) if beta_rows else None

    return {
        "total_value": total,
        "cash_value": sum(h["value"] for h in holdings if h["cash"]),
        "unrealized_gain": gain,
        "unrealized_gain_pct": gain / basis * 100 if basis else 0.0,
        "positions": sum(1 for h in holdings if not h["cash"]),
        "portfolio_beta": beta,
        "allocation": allocation,
    }


def build_snapshot(portfolio_rows: list[list], transaction_rows: list[list]) -> dict:
    holdings = parse_holdings(portfolio_rows)
    if not holdings:
        raise ValueError("No holdings found in the portfolio tab")
    summary = summarize(holdings)
    holdings.sort(key=lambda h: h["value"], reverse=True)
    return {
        "holdings": holdings,
        "summary": summary,
        "transactions": parse_transactions(transaction_rows),
    }
