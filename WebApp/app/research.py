"""Research (company analyzer) routes.

Pulls SEC XBRL facts and Twelve Data prices for one ticker, then returns the
analysis as JSON or as the Excel report. Every route lives under /api/research
so it can't clash with the portfolio routes in main.py.
"""
from __future__ import annotations

from dataclasses import asdict
from threading import Lock
from time import monotonic
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response

from src.analysis_service import AnalysisService
from src.config import load_settings
from src.excel_report import build_report_bytes
from src.models import AnalysisResult
from src.ratios import RATIO_DEFINITIONS, ttm, ttm_free_cash_flow
from src.sec_client import SecDataError
from src.twelve_data_client import MarketDataError


# Results are reused for an hour so repeat lookups don't spend API quota.
CACHE_SECONDS = 3600
CACHE_LIMIT = 100

TICKER_PATTERN = r"^[A-Za-z0-9.\-]{1,10}$"

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "spreadsheetml.sheet"
)


settings = load_settings()

router = APIRouter(prefix="/api/research")

_cache: dict[tuple[str, int], tuple[float, AnalysisResult]] = {}
_cache_lock = Lock()


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "server_keys": settings.is_ready,
    }


@router.get("/analyze")
def analyze(
    ticker: str = Query(..., pattern=TICKER_PATTERN),
    quarters: int = Query(20, ge=8, le=40),
    sec_user_agent: str | None = Header(None, alias="X-SEC-User-Agent"),
    market_api_key: str | None = Header(None, alias="X-Market-Api-Key"),
) -> dict[str, Any]:
    user_agent, api_key = resolve_credentials(sec_user_agent, market_api_key)
    result = get_analysis(ticker, quarters, user_agent, api_key)
    return serialize_result(result)


@router.get("/report")
def report(
    ticker: str = Query(..., pattern=TICKER_PATTERN),
    quarters: int = Query(20, ge=8, le=40),
    sec_user_agent: str | None = Header(None, alias="X-SEC-User-Agent"),
    market_api_key: str | None = Header(None, alias="X-Market-Api-Key"),
) -> Response:
    user_agent, api_key = resolve_credentials(sec_user_agent, market_api_key)
    result = get_analysis(ticker, quarters, user_agent, api_key)

    try:
        report_bytes = build_report_bytes(result)

    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = f"{result.company.ticker}_investment_analysis.xlsx"

    return Response(
        content=report_bytes,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def resolve_credentials(
    sec_user_agent: str | None,
    market_api_key: str | None,
) -> tuple[str, str]:
    """Prefer keys entered on the page; fall back to the server's own keys."""
    user_agent = (sec_user_agent or "").strip() or settings.sec_user_agent
    api_key = (market_api_key or "").strip() or settings.twelve_data_api_key

    if "@" not in user_agent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Enter an SEC User-Agent that includes a monitored "
                "email address, such as WSUInvestmentClub/1.0 name@email.com."
            ),
        )

    if not api_key or api_key == "replace_with_your_key":
        raise HTTPException(
            status_code=400,
            detail="Enter your Twelve Data API key.",
        )

    return user_agent, api_key


def get_analysis(
    ticker: str,
    quarters: int,
    user_agent: str,
    api_key: str,
) -> AnalysisResult:
    key = (ticker.strip().upper(), quarters)
    now = monotonic()

    with _cache_lock:
        cached = _cache.get(key)

        if cached is not None and now - cached[0] < CACHE_SECONDS:
            return cached[1]

    service = AnalysisService(user_agent, api_key)

    try:
        result = service.analyze(key[0], quarters)

    except (SecDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    with _cache_lock:
        if len(_cache) >= CACHE_LIMIT:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            del _cache[oldest]

        _cache[key] = (monotonic(), result)

    return result


def serialize_result(
    result: AnalysisResult,
) -> dict[str, Any]:
    records = result.records
    index = len(records) - 1
    latest = result.latest

    return {
        "company": asdict(result.company),
        "summary": {
            "last_period": latest.period_label,
            "period_end": latest.period_end,
            "current_price": latest.current_price,
            "market_capitalization": latest.market_capitalization,
            "ttm_revenue": ttm(records, index, "revenue"),
            "ttm_free_cash_flow": ttm_free_cash_flow(records, index),
            "data_completeness": latest.completeness,
            "average_completeness": result.overall_completeness,
        },
        "market": result.market_snapshot,
        "records": [record.to_dict() for record in records],
        "ratio_definitions": [
            {
                "key": key,
                "category": category,
                "label": label,
                "format": number_format,
            }
            for key, category, label, _description, number_format
            in RATIO_DEFINITIONS
        ],
        "latest_ratios": result.latest_ratios,
        "ratio_history": result.ratio_history,
        "warnings": result.warnings,
    }
