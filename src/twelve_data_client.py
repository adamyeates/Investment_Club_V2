from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MarketDataError(RuntimeError):
    """Raised when market data cannot be retrieved."""


@dataclass(frozen=True)
class DailyPrice:
    trading_date: date
    open: float
    close: float


class TwelveDataClient:
    BASE_URL = "https://api.twelvedata.com"

    def __init__(
        self,
        api_key: str,
    ) -> None:
        if not api_key:
            raise ValueError("TWELVE_DATA_API_KEY is required.")

        self.api_key = api_key

    def _get(
        self,
        endpoint: str,
        **params: Any,
    ) -> dict[str, Any]:
        query = {
            **params,
            "apikey": self.api_key,
        }

        url = (
            f"{self.BASE_URL}/{endpoint}?"
            f"{urlencode(query)}"
        )

        request = Request(
            url,
            headers={"Accept": "application/json"},
        )

        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )

        except HTTPError as exc:
            raise MarketDataError(
                f"Market-data request returned HTTP {exc.code}."
            ) from exc

        except (
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            raise MarketDataError(
                f"Unable to read market data: {exc}"
            ) from exc

        if (
            payload.get("status") == "error"
            or (
                "code" in payload
                and "message" in payload
            )
        ):
            raise MarketDataError(
                str(
                    payload.get(
                        "message",
                        "Twelve Data returned an error.",
                    )
                )
            )

        return payload

    def profile(
        self,
        ticker: str,
    ) -> dict[str, Any]:
        try:
            return self._get(
                "profile",
                symbol=ticker,
            )
        except MarketDataError:
            return {}

    def quote(
        self,
        ticker: str,
    ) -> dict[str, Any]:
        return self._get(
            "quote",
            symbol=ticker,
        )

    def daily_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[DailyPrice]:
        payload = self._get(
            "time_series",
            symbol=ticker,
            interval="1day",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            outputsize="5000",
            order="asc",
        )

        prices: list[DailyPrice] = []

        for item in payload.get("values", []):
            try:
                prices.append(
                    DailyPrice(
                        trading_date=date.fromisoformat(
                            str(item["datetime"])[:10]
                        ),
                        open=float(item["open"]),
                        close=float(item["close"]),
                    )
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

        prices.sort(
            key=lambda value: value.trading_date
        )

        return prices

    @staticmethod
    def price_on_or_before(
        prices: list[DailyPrice],
        target: date,
    ) -> DailyPrice | None:
        lower_bound = target - timedelta(days=10)

        eligible = [
            value
            for value in prices
            if lower_bound <= value.trading_date <= target
        ]

        if not eligible:
            return None

        return eligible[-1]

    @staticmethod
    def current_price(
        quote: dict[str, Any],
    ) -> float | None:
        for field in (
            "extended_price",
            "price",
            "close",
        ):
            value = float_or_none(quote.get(field))

            if value is not None and value > 0:
                return value

        return None

    @staticmethod
    def market_source_url(
        ticker: str,
    ) -> str:
        return (
            "https://twelvedata.com/markets/"
            f"{ticker.upper()}/stock"
        )


def float_or_none(
    value: Any,
) -> float | None:
    try:
        return float(value)

    except (TypeError, ValueError):
        return None