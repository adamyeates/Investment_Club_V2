from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.styles import Alignment
from openpyxl.worksheet.worksheet import Worksheet

from .config import TEMPLATE_PATH
from .models import AnalysisResult, QuarterRecord
from .ratios import RATIO_DEFINITIONS, ttm, ttm_free_cash_flow


DASHBOARD_SHEET = "Dashboard"
FINANCIAL_SHEET = "Financial Data"
RATIOS_SHEET = "Ratios & Metrics"

# The template's tables and charts are sized for rows 7-46 (40 quarters).
HEADER_ROW = 6
FIRST_DATA_ROW = 7
TEMPLATE_LAST_ROW = 46
MAX_QUARTERS = TEMPLATE_LAST_ROW - FIRST_DATA_ROW + 1

HISTORY_HEADER_ROW = 41
FIRST_HISTORY_ROW = 42

NOTES_CELL = "A20"


# Dashboard value cells. Labels are already in columns A and D of the template.
DASHBOARD_CELLS: dict[str, str] = {
    "company_name": "B6",
    "ticker": "B7",
    "company_type": "B8",
    "sector": "B9",
    "industry": "B10",
    "exchange": "B11",
    "currency": "B12",
    "units": "B13",
    "last_period": "B14",
    "period_end": "B15",
    "analysis_date": "B16",
    "average_completeness": "B17",
    "current_price": "E6",
    "todays_open": "E7",
    "latest_close": "E8",
    "market_capitalization": "E9",
    "enterprise_value": "E10",
    "ttm_revenue": "E11",
    "ttm_net_income": "E12",
    "ttm_free_cash_flow": "E13",
    "ttm_diluted_eps": "E14",
    "shares_outstanding": "E15",
    "data_completeness": "E16",
    "quarter_records": "E17",
}

SNAPSHOT_TEXT_FIELDS = (
    "company_name",
    "ticker",
    "last_period",
)

SNAPSHOT_NUMBER_FIELDS = (
    "current_price",
    "market_capitalization",
    "ttm_revenue",
    "ttm_free_cash_flow",
    "data_completeness",
)


# Financial Data columns A through AK, in template order.
FINANCIAL_COLUMNS: tuple[str, ...] = (
    "period",
    "period_end",
    "fiscal_year",
    "fiscal_quarter",
    "form",
    "filed_date",
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "diluted_eps",
    "operating_cash_flow",
    "capital_expenditures",
    "free_cash_flow",
    "cash",
    "accounts_receivable",
    "inventory",
    "current_assets",
    "current_liabilities",
    "total_assets",
    "total_debt",
    "total_liabilities",
    "shareholders_equity",
    "shares_outstanding",
    "interest_expense",
    "depreciation_amortization",
    "dividends_paid",
    "share_repurchases",
    "quarter_open",
    "quarter_close",
    "current_price",
    "market_capitalization",
    "enterprise_value",
    "accession",
    "sec_source_url",
    "market_source_url",
    "completeness",
)

URL_FIELDS = (
    "sec_source_url",
    "market_source_url",
)


def build_report_bytes(
    result: AnalysisResult,
) -> bytes:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"The Excel template was not found at {TEMPLATE_PATH}."
        )

    records = result.records[-MAX_QUARTERS:]

    if not records:
        raise ValueError(
            "The analysis contains no quarterly records to export."
        )

    workbook = load_workbook(TEMPLATE_PATH)

    fill_dashboard(
        workbook[DASHBOARD_SHEET],
        result,
        records,
    )

    fill_financial_data(
        workbook[FINANCIAL_SHEET],
        records,
    )

    fill_ratios(
        workbook[RATIOS_SHEET],
        result,
    )

    resize_charts(
        workbook[DASHBOARD_SHEET],
        FIRST_DATA_ROW + len(records) - 1,
    )

    buffer = BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


def read_dashboard_snapshot(
    report_bytes: bytes,
) -> dict[str, Any]:
    workbook = load_workbook(
        BytesIO(report_bytes),
        data_only=True,
    )

    sheet = workbook[DASHBOARD_SHEET]
    snapshot: dict[str, Any] = {}

    for key in SNAPSHOT_TEXT_FIELDS:
        value = sheet[DASHBOARD_CELLS[key]].value
        snapshot[key] = "" if value is None else str(value)

    for key in SNAPSHOT_NUMBER_FIELDS:
        snapshot[key] = number(
            sheet[DASHBOARD_CELLS[key]].value
        )

    return snapshot


def fill_dashboard(
    sheet: Worksheet,
    result: AnalysisResult,
    records: list[QuarterRecord],
) -> None:
    company = result.company
    market = result.market_snapshot
    latest = records[-1]
    index = len(records) - 1

    values: dict[str, Any] = {
        "company_name": company.company_name,
        "ticker": company.ticker,
        "company_type": company.company_type,
        "sector": company.sector,
        "industry": company.industry,
        "exchange": company.exchange,
        "currency": company.currency,
        "units": company.units,
        "last_period": latest.period_label,
        "period_end": latest.period_end,
        "analysis_date": company.analysis_date,
        "average_completeness": result.overall_completeness,
        "current_price": latest.current_price,
        "todays_open": market.get("open"),
        "latest_close": market.get("close"),
        "market_capitalization": latest.market_capitalization,
        "enterprise_value": latest.enterprise_value,
        "ttm_revenue": ttm(records, index, "revenue"),
        "ttm_net_income": ttm(records, index, "net_income"),
        "ttm_free_cash_flow": ttm_free_cash_flow(records, index),
        "ttm_diluted_eps": ttm(records, index, "diluted_eps"),
        "shares_outstanding": latest.shares_outstanding,
        "data_completeness": latest.completeness,
        "quarter_records": len(records),
    }

    for key, cell in DASHBOARD_CELLS.items():
        sheet[cell] = blank_to_none(values.get(key))

    notes = sheet[NOTES_CELL]

    if result.warnings:
        notes.value = "\n".join(
            f"• {warning}"
            for warning in result.warnings
        )
    else:
        notes.value = "No data-quality issues were flagged for this analysis."

    notes.alignment = Alignment(
        horizontal=notes.alignment.horizontal,
        vertical="top",
        wrap_text=True,
    )


def fill_financial_data(
    sheet: Worksheet,
    records: list[QuarterRecord],
) -> None:
    for offset, record in enumerate(records):
        row = FIRST_DATA_ROW + offset
        values = record.to_dict()

        for column, field in enumerate(FINANCIAL_COLUMNS, start=1):
            cell = sheet.cell(
                row=row,
                column=column,
                value=blank_to_none(values.get(field)),
            )

            if field in URL_FIELDS and cell.value:
                cell.hyperlink = str(cell.value)

    resize_table(
        sheet,
        "NormalizedQuarterlyData",
        HEADER_ROW,
        FIRST_DATA_ROW + len(records) - 1,
    )


def fill_ratios(
    sheet: Worksheet,
    result: AnalysisResult,
) -> None:
    # Latest values: one row per ratio, starting at row 7. The template
    # pre-formats column C in RATIO_DEFINITIONS order.
    for offset, (
        key,
        category,
        label,
        _description,
        _number_format,
    ) in enumerate(RATIO_DEFINITIONS):
        row = FIRST_DATA_ROW + offset

        sheet.cell(row=row, column=1, value=category)
        sheet.cell(row=row, column=2, value=label)
        sheet.cell(
            row=row,
            column=3,
            value=result.latest_ratios.get(key),
        )

    # Quarterly history: period, period end, then every ratio in
    # RATIO_DEFINITIONS order (columns C through AE).
    history = result.ratio_history[-MAX_QUARTERS:]
    ratio_keys = [definition[0] for definition in RATIO_DEFINITIONS]

    for offset, values in enumerate(history):
        row = FIRST_HISTORY_ROW + offset

        sheet.cell(row=row, column=1, value=values.get("period"))
        sheet.cell(row=row, column=2, value=values.get("period_end"))

        for column, key in enumerate(ratio_keys, start=3):
            sheet.cell(
                row=row,
                column=column,
                value=values.get(key),
            )

    resize_table(
        sheet,
        "QuarterlyRatioHistory",
        HISTORY_HEADER_ROW,
        FIRST_HISTORY_ROW + max(len(history), 1) - 1,
    )


def resize_table(
    sheet: Worksheet,
    table_name: str,
    header_row: int,
    last_row: int,
) -> None:
    """Shrink a template table so it ends at the last populated row."""
    table = sheet.tables[table_name]
    start, end = table.ref.split(":")
    last_column = end.rstrip("0123456789")

    ref = f"{start}:{last_column}{max(last_row, header_row + 1)}"

    table.ref = ref

    if table.autoFilter is not None:
        table.autoFilter.ref = ref


def resize_charts(
    sheet: Worksheet,
    last_row: int,
) -> None:
    """Point the Dashboard charts at only the populated Financial Data rows."""
    old_end = f"${TEMPLATE_LAST_ROW}"
    new_end = f"${last_row}"

    for chart in sheet._charts:
        for series in chart.series:
            references = []

            if series.val is not None:
                references.append(series.val.numRef)

            if series.cat is not None:
                references.extend(
                    [series.cat.numRef, series.cat.strRef]
                )

            for reference in references:
                if reference is None or not reference.f:
                    continue

                reference.f = reference.f.replace(old_end, new_end)

                # Drop cached template values so Excel redraws from the cells.
                if hasattr(reference, "numCache"):
                    reference.numCache = None

                if hasattr(reference, "strCache"):
                    reference.strCache = None


def blank_to_none(
    value: Any,
) -> Any:
    if isinstance(value, str) and not value.strip():
        return None

    return value


def number(
    value: Any,
) -> float | None:
    try:
        return float(value)

    except (TypeError, ValueError):
        return None