from __future__ import annotations

from typing import Any

from .models import QuarterRecord


RATIO_DEFINITIONS = [
    ("gross_margin", "Profitability", "Gross Margin", "", "percent"),
    ("operating_margin", "Profitability", "Operating Margin", "", "percent"),
    ("net_margin", "Profitability", "Net Margin", "", "percent"),
    ("ocf_margin", "Profitability", "Operating Cash Flow Margin", "", "percent"),
    ("fcf_margin", "Profitability", "Free Cash Flow Margin", "", "percent"),
    ("revenue_growth_qoq", "Growth", "Revenue Growth QoQ", "", "percent"),
    ("revenue_growth_yoy", "Growth", "Revenue Growth YoY", "", "percent"),
    ("eps_growth_yoy", "Growth", "Diluted EPS Growth YoY", "", "percent"),
    ("roa_ttm", "Returns", "Return on Assets (TTM)", "", "percent"),
    ("roe_ttm", "Returns", "Return on Equity (TTM)", "", "percent"),
    ("current_ratio", "Liquidity", "Current Ratio", "", "multiple"),
    ("cash_ratio", "Liquidity", "Cash Ratio", "", "multiple"),
    ("debt_to_equity", "Leverage", "Debt / Equity", "", "multiple"),
    ("debt_to_assets", "Leverage", "Debt / Assets", "", "percent"),
    ("net_debt", "Leverage", "Net Debt", "", "amount"),
    (
        "net_debt_to_operating_income",
        "Leverage",
        "Net Debt / Operating Income (TTM)",
        "",
        "multiple",
    ),
    (
        "interest_coverage",
        "Leverage",
        "Interest Coverage (TTM)",
        "",
        "multiple",
    ),
    ("asset_turnover", "Efficiency", "Asset Turnover (TTM)", "", "multiple"),
    (
        "inventory_turnover",
        "Efficiency",
        "Inventory Turnover (TTM)",
        "",
        "multiple",
    ),
    ("days_inventory", "Efficiency", "Days Inventory", "", "days"),
    (
        "free_cash_flow_ttm",
        "Cash Flow",
        "Free Cash Flow (TTM)",
        "",
        "amount",
    ),
    (
        "fcf_conversion",
        "Cash Flow",
        "FCF Conversion (TTM)",
        "",
        "percent",
    ),
    ("pe_ttm", "Valuation", "Price / Earnings (TTM)", "", "multiple"),
    (
        "p_fcf_ttm",
        "Valuation",
        "Price / Free Cash Flow (TTM)",
        "",
        "multiple",
    ),
    ("fcf_yield", "Valuation", "Free Cash Flow Yield", "", "percent"),
    (
        "ev_sales",
        "Valuation",
        "Enterprise Value / Sales (TTM)",
        "",
        "multiple",
    ),
    (
        "ev_operating_income",
        "Valuation",
        "EV / Operating Income (TTM)",
        "",
        "multiple",
    ),
    ("price_to_book", "Valuation", "Price / Book", "", "multiple"),
    (
        "data_completeness",
        "Data Quality",
        "Data Completeness",
        "",
        "percent",
    ),
]


def calculate_ratio_history(
    records: list[QuarterRecord],
) -> list[dict[str, Any]]:
    ordered = sorted(
        records,
        key=lambda record: record.period_end,
    )

    history: list[dict[str, Any]] = []

    for index, record in enumerate(ordered):
        free_cash_flow = record.free_cash_flow
        ttm_revenue = ttm(ordered, index, "revenue")
        ttm_operating_income = ttm(
            ordered,
            index,
            "operating_income",
        )
        ttm_net_income = ttm(
            ordered,
            index,
            "net_income",
        )
        ttm_interest = ttm(
            ordered,
            index,
            "interest_expense",
        )
        ttm_fcf = ttm_free_cash_flow(
            ordered,
            index,
        )
        average_assets = average_balance(
            ordered,
            index,
            "total_assets",
        )
        average_equity = average_balance(
            ordered,
            index,
            "shareholders_equity",
        )
        average_inventory = average_balance(
            ordered,
            index,
            "inventory",
        )
        ttm_gross_profit = ttm(
            ordered,
            index,
            "gross_profit",
        )

        ttm_cogs = None

        if (
            ttm_revenue is not None
            and ttm_gross_profit is not None
        ):
            ttm_cogs = ttm_revenue - ttm_gross_profit

        inventory_turnover = divide(
            ttm_cogs,
            average_inventory,
        )

        net_debt = None

        if (
            record.total_debt is not None
            and record.cash is not None
        ):
            net_debt = record.total_debt - record.cash

        row: dict[str, Any] = {
            "period": record.period_label,
            "period_end": record.period_end,
            "gross_margin": divide(
                record.gross_profit,
                record.revenue,
            ),
            "operating_margin": divide(
                record.operating_income,
                record.revenue,
            ),
            "net_margin": divide(
                record.net_income,
                record.revenue,
            ),
            "ocf_margin": divide(
                record.operating_cash_flow,
                record.revenue,
            ),
            "fcf_margin": divide(
                free_cash_flow,
                record.revenue,
            ),
            "revenue_growth_qoq": growth(
                record.revenue,
                prior(
                    ordered,
                    index,
                    1,
                    "revenue",
                ),
            ),
            "revenue_growth_yoy": growth(
                record.revenue,
                prior(
                    ordered,
                    index,
                    4,
                    "revenue",
                ),
            ),
            "eps_growth_yoy": growth(
                record.diluted_eps,
                prior(
                    ordered,
                    index,
                    4,
                    "diluted_eps",
                ),
            ),
            "roa_ttm": divide(
                ttm_net_income,
                average_assets,
            ),
            "roe_ttm": divide(
                ttm_net_income,
                average_equity,
            ),
            "current_ratio": divide(
                record.current_assets,
                record.current_liabilities,
            ),
            "cash_ratio": divide(
                record.cash,
                record.current_liabilities,
            ),
            "debt_to_equity": divide(
                record.total_debt,
                record.shareholders_equity,
            ),
            "debt_to_assets": divide(
                record.total_debt,
                record.total_assets,
            ),
            "net_debt": net_debt,
            "net_debt_to_operating_income": divide(
                net_debt,
                ttm_operating_income,
            ),
            "interest_coverage": divide(
                ttm_operating_income,
                ttm_interest,
            ),
            "asset_turnover": divide(
                ttm_revenue,
                average_assets,
            ),
            "inventory_turnover": inventory_turnover,
            "days_inventory": divide(
                365.0,
                inventory_turnover,
            ),
            "free_cash_flow_ttm": ttm_fcf,
            "fcf_conversion": divide(
                ttm_fcf,
                ttm_net_income,
            ),
            "pe_ttm": divide(
                record.market_capitalization,
                ttm_net_income,
            ),
            "p_fcf_ttm": divide(
                record.market_capitalization,
                ttm_fcf,
            ),
            "fcf_yield": divide(
                ttm_fcf,
                record.market_capitalization,
            ),
            "ev_sales": divide(
                record.enterprise_value,
                ttm_revenue,
            ),
            "ev_operating_income": divide(
                record.enterprise_value,
                ttm_operating_income,
            ),
            "price_to_book": divide(
                record.market_capitalization,
                record.shareholders_equity,
            ),
            "data_completeness": record.completeness,
        }

        history.append(row)

    return history


def latest_ratio_values(
    history: list[dict[str, Any]],
) -> dict[str, float | None]:
    if not history:
        return {
            definition[0]: None
            for definition in RATIO_DEFINITIONS
        }

    latest = history[-1]

    return {
        key: latest.get(key)
        for key, *_ in RATIO_DEFINITIONS
    }


def ttm(
    records: list[QuarterRecord],
    index: int,
    field: str,
) -> float | None:
    if index < 3:
        return None

    values = [
        getattr(records[position], field)
        for position in range(index - 3, index + 1)
    ]

    if any(value is None for value in values):
        return None

    return sum(
        float(value)
        for value in values
        if value is not None
    )


def ttm_free_cash_flow(
    records: list[QuarterRecord],
    index: int,
) -> float | None:
    if index < 3:
        return None

    values = [
        records[position].free_cash_flow
        for position in range(index - 3, index + 1)
    ]

    if any(value is None for value in values):
        return None

    return sum(
        float(value)
        for value in values
        if value is not None
    )


def average_balance(
    records: list[QuarterRecord],
    index: int,
    field: str,
) -> float | None:
    current = getattr(records[index], field)

    if current is None:
        return None

    prior_value = (
        getattr(records[index - 4], field)
        if index >= 4
        else None
    )

    if prior_value is None:
        return float(current)

    return (
        float(current)
        + float(prior_value)
    ) / 2.0


def prior(
    records: list[QuarterRecord],
    index: int,
    offset: int,
    field: str,
) -> float | None:
    if index < offset:
        return None

    return getattr(
        records[index - offset],
        field,
    )


def growth(
    current: float | None,
    prior_value: float | None,
) -> float | None:
    if (
        current is None
        or prior_value is None
        or prior_value == 0
    ):
        return None

    return current / abs(prior_value) - 1.0


def divide(
    numerator: float | None,
    denominator: float | None,
) -> float | None:
    if (
        numerator is None
        or denominator is None
        or denominator == 0
    ):
        return None

    return numerator / denominator