from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .models import AnalysisResult
from .normalization import normalize_sec_company
from .ratios import (
    calculate_ratio_history,
    latest_ratio_values,
)
from .sec_client import SecClient
from .twelve_data_client import TwelveDataClient


class AnalysisService:
    def __init__(
        self,
        sec_user_agent: str,
        market_api_key: str,
    ) -> None:
        self.sec = SecClient(sec_user_agent)
        self.market = TwelveDataClient(market_api_key)

    def analyze(
        self,
        ticker: str,
        quarter_limit: int = 20,
    ) -> AnalysisResult:
        ticker = (
            ticker.strip()
            .upper()
            .replace(".", "-")
        )

        sec_payload = self.sec.fetch_company(ticker)

        company, records, warnings = normalize_sec_company(
            sec_payload,
            quarter_limit,
        )

        if not records:
            raise ValueError(
                "The SEC returned no usable quarterly "
                "XBRL records for this ticker."
            )

        profile = self.market.profile(ticker)
        quote = self.market.quote(ticker)

        self.apply_company_metadata(
            company,
            profile,
            quote,
        )

        start_date = (
            records[0].period_end
            - timedelta(days=10)
        )

        history = self.market.daily_history(
            ticker,
            start_date,
            date.today(),
        )

        market_url = self.market.market_source_url(ticker)

        for record in records:
            price = self.market.price_on_or_before(
                history,
                record.period_end,
            )

            if price is not None:
                record.quarter_open = price.open
                record.quarter_close = price.close

            record.market_source_url = market_url

        current_price = self.market.current_price(quote)

        latest = records[-1]
        latest.current_price = current_price

        for record in records:
            if (
                record is latest
                and current_price is not None
            ):
                price_for_value = current_price
            else:
                price_for_value = record.quarter_close

            if (
                price_for_value is not None
                and record.shares_outstanding is not None
            ):
                record.market_capitalization = (
                    price_for_value
                    * record.shares_outstanding
                )

                debt = record.total_debt or 0.0
                cash = record.cash or 0.0

                record.enterprise_value = (
                    record.market_capitalization
                    + debt
                    - cash
                )

        security_type = company.company_type.lower()

        if any(
            value in security_type
            for value in (
                "etf",
                "fund",
                "trust",
                "index",
            )
        ):
            warnings.append(
                "This security is not an operating company. "
                "Corporate ratios may be incomplete or misleading."
            )

        ratio_history = calculate_ratio_history(records)

        return AnalysisResult(
            company=company,
            records=records,
            ratio_history=ratio_history,
            latest_ratios=latest_ratio_values(
                ratio_history
            ),
            warnings=warnings,
            market_snapshot={
                "open": number(quote.get("open")),
                "close": number(quote.get("close")),
                "current": current_price,
                "is_market_open": (
                    str(
                        quote.get(
                            "is_market_open",
                            "",
                        )
                    ).lower()
                    == "true"
                ),
                "datetime": (
                    quote.get("datetime")
                    or quote.get("timestamp")
                    or ""
                ),
            },
        )

    @staticmethod
    def apply_company_metadata(
        company: Any,
        profile: dict[str, Any],
        quote: dict[str, Any],
    ) -> None:
        company.company_name = str(
            profile.get("name")
            or quote.get("name")
            or company.company_name
        )

        raw_type = str(
            profile.get("type")
            or quote.get("type")
            or "Common Stock"
        )

        if "stock" in raw_type.lower():
            company.company_type = "Operating Company"
        else:
            company.company_type = raw_type

        company.sector = str(
            profile.get("sector")
            or ""
        )

        company.industry = str(
            profile.get("industry")
            or ""
        )

        company.currency = str(
            profile.get("currency")
            or quote.get("currency")
            or company.currency
        )

        company.exchange = str(
            profile.get("exchange")
            or quote.get("exchange")
            or ""
        )

        company.units = (
            f"{company.currency} actuals; "
            "shares actual; "
            f"per-share {company.currency}"
        )


def number(
    value: Any,
) -> float | None:
    try:
        return float(value)

    except (TypeError, ValueError):
        return None