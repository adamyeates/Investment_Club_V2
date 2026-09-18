from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook.properties import CalcProperties

from .config import TEMPLATE_PATH
from .models import AnalysisResult
from .ratios import RATIO_DEFINITIONS


REQUIRED_SHEETS = {
    "Dashboard",
    "Financial Data",
    "Ratios & Metrics",
}


FINANCIAL_COLUMNS = [
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
]


def build_report_bytes(
    result: AnalysisResult,
    template_path: Path = TEMPLATE_PATH,
) -> bytes:
    if not template_path.exists():
        raise FileNotFoundError(
            f"Excel template not found: {template_path}"
        )

    workbook = load_workbook(template_path)

    missing_sheets = REQUIRED_SHEETS.difference(
        workbook.sheetnames
    )

    if missing_sheets:
        workbook.close()

        missing_names = ", ".join(
            sorted(missing_sheets)
        )

        raise ValueError(
            "The Excel template is missing these "
            f"worksheets: {missing_names}"
        )

    write_dashboard(
        workbook["Dashboard"],
        result,
    )

    write_financial_data(
        workbook["Financial Data"],
        result,
    )

    write_ratios(
        workbook["Ratios & Metrics"],
        result,
    )

    if workbook.calculation is None:
        workbook.calculation = CalcProperties()

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"

    output = BytesIO()
    workbook.save(output)
    workbook.close()

    return output.getvalue()


def read_dashboard_snapshot(
    report_bytes: bytes,
) -> dict[str, Any]:
    workbook = load_workbook(
        BytesIO(report_bytes),
        data_only=True,
        read_only=True,
    )

    sheet = workbook["Dashboard"]

    snapshot = {
        "company_name": sheet["B6"].value,
        "ticker": sheet["B7"].value,
        "last_period": sheet["B14"].value,
        "current_price": sheet["E6"].value,
        "market_capitalization": sheet["E9"].value,
        "enterprise_value": sheet["E10"].value,
        "ttm_revenue": sheet["E11"].value,
        "ttm_net_income": sheet["E12"].value,
        "ttm_free_cash_flow": sheet["E13"].value,
        "data_completeness": sheet["B17"].value,
    }

    workbook.close()
    return snapshot


def write_dashboard(
    sheet: Any,
    result: AnalysisResult,
) -> None:
    latest = result.latest
    company = result.company
    market = result.market_snapshot
    latest_ratios = result.latest_ratios

    identity_values = {
        "B6": company.company_name,
        "B7": company.ticker,
        "B8": company.company_type,
        "B9": company.sector,
        "B10": company.industry,
        "B11": company.exchange,
        "B12": company.currency,
        "B13": company.units,
        "B14": latest.period_label,
        "B15": latest.period_end,
        "B16": company.analysis_date,
        "B17": result.overall_completeness,
    }

    for cell_reference, value in identity_values.items():
        sheet[cell_reference] = value

    kpi_values = {
        "E6": market.get("current"),
        "E7": market.get("open"),
        "E8": market.get("close"),
        "E9": latest.market_capitalization,
        "E10": latest.enterprise_value,
        "E11": trailing_four_quarters(
            result,
            "revenue",
        ),
        "E12": trailing_four_quarters(
            result,
            "net_income",
        ),
        "E13": latest_ratios.get(
            "free_cash_flow_ttm"
        ),
        "E14": trailing_four_quarters(
            result,
            "diluted_eps",
        ),
        "E15": latest.shares_outstanding,
        "E16": latest.completeness,
        "E17": len(result.records),
    }

    for cell_reference, value in kpi_values.items():
        sheet[cell_reference] = value

    if result.warnings:
        sheet["A20"] = " | ".join(result.warnings)
    else:
        sheet["A20"] = (
            "No automated data-quality warnings."
        )


def write_financial_data(
    sheet: Any,
    result: AnalysisResult,
) -> None:
    clear_values(
        sheet,
        min_row=7,
        max_row=46,
        min_col=1,
        max_col=37,
    )

    records = result.records[-40:]

    for row_number, record in enumerate(
        records,
        start=7,
    ):
        values = record.to_dict()

        for column_number, field in enumerate(
            FINANCIAL_COLUMNS,
            start=1,
        ):
            cell = sheet.cell(
                row=row_number,
                column=column_number,
            )

            cell.value = values.get(field)

            if (
                field
                in {
                    "sec_source_url",
                    "market_source_url",
                }
                and cell.value
            ):
                cell.hyperlink = str(cell.value)
                cell.style = "Hyperlink"


def write_ratios(
    sheet: Any,
    result: AnalysisResult,
) -> None:
    clear_values(
        sheet,
        min_row=7,
        max_row=35,
        min_col=1,
        max_col=5,
    )

    for row_number, definition in enumerate(
        RATIO_DEFINITIONS,
        start=7,
    ):
        (
            key,
            category,
            label,
            _description,
            _number_format,
        ) = definition

        sheet.cell(
            row=row_number,
            column=1,
            value=category,
        )

        sheet.cell(
            row=row_number,
            column=2,
            value=label,
        )

        sheet.cell(
            row=row_number,
            column=3,
            value=result.latest_ratios.get(key),
        )

    clear_values(
        sheet,
        min_row=42,
        max_row=81,
        min_col=1,
        max_col=31,
    )

    ratio_history = result.ratio_history[-40:]

    for row_number, row_values in enumerate(
        ratio_history,
        start=42,
    ):
        sheet.cell(
            row=row_number,
            column=1,
            value=row_values.get("period"),
        )

        sheet.cell(
            row=row_number,
            column=2,
            value=row_values.get("period_end"),
        )

        for column_number, definition in enumerate(
            RATIO_DEFINITIONS,
            start=3,
        ):
            key = definition[0]

            sheet.cell(
                row=row_number,
                column=column_number,
                value=row_values.get(key),
            )


def trailing_four_quarters(
    result: AnalysisResult,
    field: str,
) -> float | None:
    records = result.records[-4:]

    if len(records) != 4:
        return None

    values = [
        getattr(record, field)
        for record in records
    ]

    if any(value is None for value in values):
        return None

    return sum(
        float(value)
        for value in values
        if value is not None
    )


def clear_values(
    sheet: Any,
    min_row: int,
    max_row: int,
    min_col: int,
    max_col: int,
) -> None:
    for row in sheet.iter_rows(
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
    ):
        for cell in row:
            cell.value = None
            cell.hyperlink = None