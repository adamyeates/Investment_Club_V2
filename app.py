from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis_service import AnalysisService
from src.config import load_settings
from src.excel_report import build_report_bytes, read_dashboard_snapshot
from src.ratios import RATIO_DEFINITIONS
from src.sec_client import SecDataError
from src.twelve_data_client import MarketDataError


st.set_page_config(
    page_title="Investment Club Company Analyzer",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(ttl=3600, show_spinner=False)
def run_analysis(
    ticker: str,
    quarters: int,
    sec_user_agent: str,
    market_api_key: str,
):
    service = AnalysisService(sec_user_agent, market_api_key)
    return service.analyze(ticker, quarters)


def main() -> None:
    settings = load_settings()

    st.title("Investment Club Company Analyzer")
    st.caption(
        "SEC filing data and Twelve Data market information organized into "
        "financial metrics, ratios, charts, and an Excel report."
    )

    with st.sidebar:
        st.header("Configuration")

        sec_user_agent = st.text_input(
            "SEC User-Agent",
            value=settings.sec_user_agent,
            help=(
                "Enter an application name and monitored email address, such as "
                "WeberStateInvestmentClub/1.0 name@email.com."
            ),
        )

        market_api_key = st.text_input(
            "Twelve Data API key",
            value=settings.twelve_data_api_key,
            type="password",
        )

        quarters = st.slider(
            "Quarters to analyze",
            min_value=8,
            max_value=40,
            value=settings.default_quarters,
            step=4,
        )

        st.caption(
            "The generated workbook stays in memory. The program does not "
            "create company tabs or retain prior ticker information."
        )

    ticker = st.text_input(
        "Ticker",
        placeholder="AAPL",
    ).strip().upper()

    analyze = st.button(
        "Analyze company",
        type="primary",
        use_container_width=True,
    )

    if not analyze:
        show_starting_notes()
        return

    if not ticker:
        st.error("Enter a ticker symbol.")
        return

    if "@" not in sec_user_agent:
        st.error("The SEC User-Agent must include a monitored email address.")
        return

    if not market_api_key or market_api_key == "replace_with_your_key":
        st.error("Add your Twelve Data API key in the sidebar or .env file.")
        return

    try:
        with st.spinner(f"Reading SEC filings and market data for {ticker}..."):
            result = run_analysis(
                ticker,
                quarters,
                sec_user_agent,
                market_api_key,
            )
            report_bytes = build_report_bytes(result)
            snapshot = read_dashboard_snapshot(report_bytes)

    except (
        SecDataError,
        MarketDataError,
        ValueError,
        FileNotFoundError,
    ) as exc:
        st.error(str(exc))
        return

    except Exception as exc:
        st.exception(exc)
        return

    show_header(result, snapshot)

    for warning in result.warnings:
        st.warning(warning)

    overview_tab, financials_tab, ratios_tab, excel_tab = st.tabs(
        [
            "Overview",
            "Financial statements",
            "Ratios",
            "Excel report",
        ]
    )

    with overview_tab:
        show_charts(result)

    with financials_tab:
        show_financials(result)

    with ratios_tab:
        show_ratios(result)

    with excel_tab:
        show_excel_download(result, report_bytes)


def show_starting_notes() -> None:
    st.info(
        "Enter a U.S.-listed operating-company ticker and select "
        "**Analyze company**."
    )

    columns = st.columns(3)

    columns[0].markdown(
        "**SEC filing data**\n\n"
        "Standardized facts from company 10-K and 10-Q filings."
    )

    columns[1].markdown(
        "**Market data**\n\n"
        "Current quote and historical quarter-end market prices."
    )

    columns[2].markdown(
        "**Outputs**\n\n"
        "Financial ratios, three charts, and an Excel report."
    )


def show_header(
    result: Any,
    snapshot: dict[str, Any],
) -> None:
    company = result.company

    st.subheader(f"{snapshot['company_name']} ({snapshot['ticker']})")

    st.caption(
        f"{company.company_type} · "
        f"{company.sector or 'Sector unavailable'} · "
        f"Latest filing period: {snapshot['last_period']}"
    )

    columns = st.columns(5)

    columns[0].metric(
        "Current price",
        money(snapshot["current_price"], company.currency),
    )

    columns[1].metric(
        "Market cap",
        compact(snapshot["market_capitalization"], company.currency),
    )

    columns[2].metric(
        "TTM revenue",
        compact(snapshot["ttm_revenue"], company.currency),
    )

    columns[3].metric(
        "TTM free cash flow",
        compact(snapshot["ttm_free_cash_flow"], company.currency),
    )

    columns[4].metric(
        "Data completeness",
        percent(snapshot["data_completeness"]),
    )


def show_charts(result: Any) -> None:
    rows = [record.to_dict() for record in result.records]
    frame = pd.DataFrame(rows)

    st.plotly_chart(
        line_chart(
            frame=frame,
            fields=[
                "revenue",
                "gross_profit",
                "operating_income",
                "net_income",
            ],
            title="Growth and profitability",
            labels=[
                "Revenue",
                "Gross profit",
                "Operating income",
                "Net income",
            ],
        ),
        use_container_width=True,
    )

    left_column, right_column = st.columns(2)

    with left_column:
        st.plotly_chart(
            line_chart(
                frame=frame,
                fields=[
                    "total_assets",
                    "total_liabilities",
                    "total_debt",
                    "cash",
                    "inventory",
                ],
                title="Balance sheet",
                labels=[
                    "Assets",
                    "Liabilities",
                    "Debt",
                    "Cash",
                    "Inventory",
                ],
            ),
            use_container_width=True,
        )

    with right_column:
        st.plotly_chart(
            line_chart(
                frame=frame,
                fields=[
                    "operating_cash_flow",
                    "capital_expenditures",
                    "free_cash_flow",
                ],
                title="Cash flow",
                labels=[
                    "Operating cash flow",
                    "Capital expenditures",
                    "Free cash flow",
                ],
            ),
            use_container_width=True,
        )


def line_chart(
    frame: pd.DataFrame,
    fields: list[str],
    title: str,
    labels: list[str],
) -> go.Figure:
    figure = go.Figure()

    for field, label in zip(fields, labels):
        figure.add_trace(
            go.Scatter(
                x=frame["period"],
                y=frame[field],
                mode="lines+markers",
                name=label,
                connectgaps=False,
            )
        )

    figure.update_layout(
        title=title,
        template="plotly_white",
        hovermode="x unified",
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        yaxis_title="Reported currency — actual units",
    )

    return figure


def show_financials(result: Any) -> None:
    fields = [
        "period",
        "period_end",
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "diluted_eps",
        "operating_cash_flow",
        "capital_expenditures",
        "free_cash_flow",
        "cash",
        "inventory",
        "total_assets",
        "total_debt",
        "shareholders_equity",
        "shares_outstanding",
        "quarter_open",
        "quarter_close",
    ]

    rows = [record.to_dict() for record in reversed(result.records)]
    frame = pd.DataFrame(rows)

    available_fields = [
        field for field in fields if field in frame.columns
    ]

    st.dataframe(
        frame[available_fields],
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Income-statement and cash-flow values are discrete quarters. "
        "Balance-sheet values represent the end of each reporting period."
    )


def show_ratios(result: Any) -> None:
    rows = []

    for (
        key,
        category,
        label,
        _description,
        number_format,
    ) in RATIO_DEFINITIONS:
        value = result.latest_ratios.get(key)

        rows.append(
            {
                "Category": category,
                "Ratio / metric": label,
                "Value": format_ratio(
                    value,
                    number_format,
                    result.company.currency,
                ),
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "TTM ratios require four complete quarters. A blank value means "
        "the required standardized facts were unavailable or the calculation "
        "would have required dividing by zero."
    )


def show_excel_download(
    result: Any,
    report_bytes: bytes,
) -> None:
    filename = f"{result.company.ticker}_investment_analysis.xlsx"

    st.subheader("Completed Excel report")

    st.write(
        "Download the completed workbook containing the Dashboard, "
        "Financial Data, and Ratios & Metrics tabs."
    )

    st.download_button(
        "Download Excel report",
        data=report_bytes,
        file_name=filename,
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        type="primary",
        use_container_width=True,
    )

    st.caption(
        "The workbook was generated in memory for this analysis. "
        "The application does not retain the company's information "
        "after the session is cleared."
    )


def format_ratio(
    value: float | None,
    number_format: str,
    currency: str,
) -> str:
    if value is None:
        return "—"

    if number_format == "percent":
        return f"{value:.1%}"

    if number_format == "multiple":
        return f"{value:.2f}×"

    if number_format == "days":
        return f"{value:.1f} days"

    return compact(value, currency)


def money(
    value: float | None,
    currency: str,
) -> str:
    if value is None:
        return "—"

    return f"{currency} {value:,.2f}"


def compact(
    value: float | None,
    currency: str,
) -> str:
    if value is None:
        return "—"

    absolute_value = abs(value)

    scales = [
        (1_000_000_000_000, "T"),
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    ]

    for divisor, suffix in scales:
        if absolute_value >= divisor:
            return f"{currency} {value / divisor:,.2f}{suffix}"

    return f"{currency} {value:,.2f}"


def percent(value: float | None) -> str:
    if value is None:
        return "—"

    return f"{value:.0%}"


if __name__ == "__main__":
    main()