from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SecDataError(RuntimeError):
    """Raised when an SEC request cannot be completed."""


@dataclass(frozen=True)
class SecCompanyPayload:
    ticker: str
    cik: int
    company_facts: dict[str, Any]
    submissions: dict[str, Any]


class SecClient:
    BASE_DATA = "https://data.sec.gov"
    TICKER_MAP_URL = (
        "https://www.sec.gov/files/company_tickers.json"
    )

    def __init__(
        self,
        user_agent: str,
        minimum_interval: float = 0.12,
    ) -> None:
        if "@" not in user_agent:
            raise ValueError(
                "SEC_USER_AGENT must identify the application "
                "and include a monitored email address."
            )

        self.user_agent = user_agent
        self.minimum_interval = max(minimum_interval, 0.11)
        self._last_request_at = 0.0
        self._ticker_map: dict[str, int] | None = None

    def _get_json(
        self,
        url: str,
    ) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_request_at

        if elapsed < self.minimum_interval:
            time.sleep(self.minimum_interval - elapsed)

        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )

        except HTTPError as exc:
            raise SecDataError(
                f"SEC returned HTTP {exc.code} for {url}."
            ) from exc

        except (
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            raise SecDataError(
                f"Unable to read SEC data from {url}: {exc}"
            ) from exc

        finally:
            self._last_request_at = time.monotonic()

        return payload

    def ticker_to_cik(
        self,
        ticker: str,
    ) -> int:
        normalized = (
            ticker.strip()
            .upper()
            .replace(".", "-")
        )

        if not normalized:
            raise SecDataError("Ticker is required.")

        if self._ticker_map is None:
            raw = self._get_json(self.TICKER_MAP_URL)

            self._ticker_map = {
                str(item["ticker"])
                .upper()
                .replace(".", "-"): int(item["cik_str"])
                for item in raw.values()
            }

        try:
            return self._ticker_map[normalized]

        except KeyError as exc:
            raise SecDataError(
                f"{ticker.upper()} was not found in the SEC ticker list. "
                "The security may be foreign, private, delisted, or a fund "
                "without comparable XBRL facts."
            ) from exc

    def fetch_company(
        self,
        ticker: str,
    ) -> SecCompanyPayload:
        cik = self.ticker_to_cik(ticker)
        cik_padded = f"{cik:010d}"

        facts = self._get_json(
            f"{self.BASE_DATA}/api/xbrl/"
            f"companyfacts/CIK{cik_padded}.json"
        )

        submissions = self._get_json(
            f"{self.BASE_DATA}/submissions/"
            f"CIK{cik_padded}.json"
        )

        return SecCompanyPayload(
            ticker=ticker.strip().upper(),
            cik=cik,
            company_facts=facts,
            submissions=submissions,
        )

    @staticmethod
    def filing_index(
        submissions: dict[str, Any],
    ) -> dict[str, dict[str, str]]:
        recent = (
            submissions
            .get("filings", {})
            .get("recent", {})
        )

        accessions = recent.get("accessionNumber", [])
        index: dict[str, dict[str, str]] = {}

        for row_number, accession in enumerate(accessions):
            index[accession] = {
                "accession": accession,
                "form": at(
                    recent.get("form", []),
                    row_number,
                ),
                "filed": at(
                    recent.get("filingDate", []),
                    row_number,
                ),
                "report_date": at(
                    recent.get("reportDate", []),
                    row_number,
                ),
                "primary_document": at(
                    recent.get("primaryDocument", []),
                    row_number,
                ),
            }

        return index

    @staticmethod
    def filing_url(
        cik: int,
        accession: str,
        primary_document: str = "",
    ) -> str:
        accession_compact = accession.replace("-", "")

        base = (
            "https://www.sec.gov/Archives/"
            f"edgar/data/{cik}/{accession_compact}"
        )

        if primary_document:
            return f"{base}/{primary_document}"

        return base


def at(
    items: list[Any],
    index: int,
) -> str:
    if index >= len(items) or items[index] is None:
        return ""

    return str(items[index])