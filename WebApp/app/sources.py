"""Ways of reading the raw rows of the two tabs we need.

Every source returns (portfolio_rows, transaction_rows): lists of rows, each row a list
of cell values, header row first. Numbers may arrive as real numbers (Sheets API,
xlsx) or as formatted text like "$1,018.30" / "-7.3%" (CSV); portfolio.py handles both.
"""
from __future__ import annotations

import csv
import io
from typing import Protocol

import httpx

from . import config

Rows = list[list]


class Source(Protocol):
    name: str

    def fetch(self) -> tuple[Rows, Rows]: ...


class SheetsApiSource:
    """Google Sheets API v4 through gspread, authenticated as a service account.

    Both tabs are read in ONE batch request, so polling every 60 s uses ~1 request/min,
    far inside the free quota.
    """

    name = "Google Sheets API"

    def __init__(self) -> None:
        import gspread  # imported here so the other sources work without it installed

        if not config.SPREADSHEET_ID:
            raise RuntimeError("SPREADSHEET_ID is not set")
        client = gspread.service_account(filename=config.GOOGLE_CREDENTIALS_FILE)
        self._sheet = client.open_by_key(config.SPREADSHEET_ID)

    def fetch(self) -> tuple[Rows, Rows]:
        ranges = [f"'{config.PORTFOLIO_TAB}'!A1:Z200", f"'{config.TRANSACTIONS_TAB}'!A1:H2000"]
        result = self._sheet.values_batch_get(
            ranges,
            params={
                # real numbers (percent cells come back as fractions, e.g. -0.073)
                "valueRenderOption": "UNFORMATTED_VALUE",
                # but dates as readable text instead of serial numbers
                "dateTimeRenderOption": "FORMATTED_STRING",
            },
        )
        value_ranges = result.get("valueRanges", [])
        portfolio = value_ranges[0].get("values", []) if len(value_ranges) > 0 else []
        transactions = value_ranges[1].get("values", []) if len(value_ranges) > 1 else []
        return portfolio, transactions


class CsvSource:
    """Published-to-web CSV links. No credentials, but Google caches them for ~5 minutes."""

    name = "published CSV"

    def __init__(self) -> None:
        if not config.PORTFOLIO_CSV_URL:
            raise RuntimeError("PORTFOLIO_CSV_URL is not set")
        self._client = httpx.Client(timeout=20, follow_redirects=True)

    def _get(self, url: str) -> Rows:
        if not url:
            return []
        resp = self._client.get(url)
        resp.raise_for_status()
        return [row for row in csv.reader(io.StringIO(resp.text))]

    def fetch(self) -> tuple[Rows, Rows]:
        return self._get(config.PORTFOLIO_CSV_URL), self._get(config.TRANSACTIONS_CSV_URL)


class XlsxSource:
    """A downloaded copy of the sheet. Uses the values Google last calculated, so prices
    are frozen at export time. For local development and tests only."""

    name = "local xlsx"

    def __init__(self, path: str | None = None) -> None:
        self._path = path or config.XLSX_PATH
        if not self._path:
            raise RuntimeError("XLSX_PATH is not set")

    def fetch(self) -> tuple[Rows, Rows]:
        import openpyxl

        wb = openpyxl.load_workbook(self._path, data_only=True, read_only=True)
        try:
            def rows(tab: str) -> Rows:
                if tab not in wb.sheetnames:
                    return []
                return [list(r) for r in wb[tab].iter_rows(values_only=True)]

            return rows(config.PORTFOLIO_TAB), rows(config.TRANSACTIONS_TAB)
        finally:
            wb.close()


def make_source() -> Source:
    if config.SOURCE == "csv":
        return CsvSource()
    if config.SOURCE == "xlsx":
        return XlsxSource()
    if config.SOURCE == "sheets_api":
        return SheetsApiSource()
    raise RuntimeError(f"Unknown SOURCE '{config.SOURCE}' (use sheets_api, csv or xlsx)")
