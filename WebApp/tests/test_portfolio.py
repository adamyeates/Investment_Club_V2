import os
from pathlib import Path

import pytest

SAMPLE = Path(__file__).parent / "sample_portfolio.xlsx"
os.environ["SOURCE"] = "xlsx"
os.environ["XLSX_PATH"] = str(SAMPLE)
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["WEBHOOK_DELAY_SECONDS"] = "0"

from app.portfolio import build_snapshot, to_number, to_percent  # noqa: E402
from app.sources import XlsxSource  # noqa: E402


def test_number_parsing():
    assert to_number("$1,018.30") == 1018.30
    assert to_number("(12.50)") == -12.5
    assert to_number("#N/A") is None
    assert to_number("") is None
    assert to_percent("-7.28%") == -7.28
    assert to_percent(-0.0728) == pytest.approx(-7.28)


def test_snapshot_from_sample_sheet():
    snap = build_snapshot(*XlsxSource(str(SAMPLE)).fetch())
    syms = [h["sym"] for h in snap["holdings"]]
    assert len(syms) == 20
    assert "YTD" not in syms and "Since September 2025" not in syms  # rows below the holdings
    s = snap["summary"]
    assert s["total_value"] == pytest.approx(101443.10, abs=0.01)  # matches the sheet's total row
    assert s["positions"] == 18  # CASH and VUSXX excluded
    assert sum(a["pct"] for a in s["allocation"]) == pytest.approx(100)
    aapl = next(h for h in snap["holdings"] if h["sym"] == "AAPL")
    assert aapl["value"] == pytest.approx(5913.62)
    assert aapl["ytd"] == pytest.approx(28.36, abs=0.01)
    cash = next(h for h in snap["holdings"] if h["sym"] == "CASH")
    assert cash["shares"] is None and cash["ret"] is None
    tx = snap["transactions"]
    assert tx[0]["date"] == "2026-10-14" and tx[0]["sym"] == "INTC" and tx[0]["action"] == "SELL"
    assert all(t["shares"] >= 0 for t in tx if t["shares"] is not None)


def test_csv_style_rows():
    """The published-CSV source delivers formatted text; it must parse the same way."""
    portfolio = [
        ["Symbol", "Name", "Last Price $", "Quantity", "Price Paid $", "YTD %", "Value $", "Sector"],
        ["AAPL", "Apple", "$347.86", "17", "$27.53", "28.36%", "$5,913.62", "Technology"],
        ["CASH", "CASH", "$1.00", "235.39", "$1.00", "0.00%", "$5,061.24", "CASH"],
        ["", "", "", "", "", "", "$10,974.86", ""],
        ["YTD", "12.16%", "11.95%", "", "", "", "", ""],
    ]
    tx = [["Date", "Ticker", "Action", "Quantity", "Price", "Value"],
          ["10/14/2026", "INTC", "SELL", "23", "$99.53", "$2,289.14"]]
    snap = build_snapshot(portfolio, tx)
    assert [h["sym"] for h in snap["holdings"]] == ["AAPL", "CASH"]  # largest first
    assert snap["holdings"][0]["ytd"] == pytest.approx(28.36)
    assert snap["transactions"][0]["date"] == "2026-10-14"


def test_api_and_webhook():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["version"] and len(body["holdings"]) == 20
        assert client.post("/api/webhook/sheet-changed").status_code == 401
        assert client.post("/api/webhook/sheet-changed", headers={"X-Webhook-Secret": "nope"}).status_code == 401
        assert client.post("/api/webhook/sheet-changed", headers={"X-Webhook-Secret": "test-secret"}).status_code == 200
        assert client.post("/api/webhook/sheet-changed", json={"secret": "test-secret"}).status_code == 200
        assert client.get("/api/health").json()["ok"] is True
        assert "Recent trades" in client.get("/").text
