from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


FINANCIAL_FIELDS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "diluted_eps",
    "operating_cash_flow",
    "capital_expenditures",
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
)


@dataclass
class CompanyInfo:
    ticker: str
    company_name: str
    company_type: str = "Operating Company"
    sector: str = ""
    industry: str = ""
    currency: str = "USD"
    units: str = "Reported currency, actual units"
    exchange: str = ""
    cik: str = ""
    analysis_date: date = field(default_factory=date.today)


@dataclass
class QuarterRecord:
    fiscal_year: int
    fiscal_quarter: int
    period_end: date
    form: str = ""
    filed_date: date | None = None
    accession: str = ""
    sec_source_url: str = ""
    market_source_url: str = ""

    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    diluted_eps: float | None = None
    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None

    cash: float | None = None
    accounts_receivable: float | None = None
    inventory: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    total_assets: float | None = None
    total_debt: float | None = None
    total_liabilities: float | None = None
    shareholders_equity: float | None = None
    shares_outstanding: float | None = None

    interest_expense: float | None = None
    depreciation_amortization: float | None = None
    dividends_paid: float | None = None
    share_repurchases: float | None = None

    quarter_open: float | None = None
    quarter_close: float | None = None
    current_price: float | None = None
    market_capitalization: float | None = None
    enterprise_value: float | None = None
    completeness: float = 0.0

    @property
    def period_label(self) -> str:
        return f"FY{self.fiscal_year} Q{self.fiscal_quarter}"

    @property
    def free_cash_flow(self) -> float | None:
        if (
            self.operating_cash_flow is None
            or self.capital_expenditures is None
        ):
            return None

        return self.operating_cash_flow - abs(self.capital_expenditures)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["period"] = self.period_label
        row["free_cash_flow"] = self.free_cash_flow
        return row


@dataclass
class AnalysisResult:
    company: CompanyInfo
    records: list[QuarterRecord]
    ratio_history: list[dict[str, Any]]
    latest_ratios: dict[str, float | None]
    warnings: list[str] = field(default_factory=list)
    market_snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def latest(self) -> QuarterRecord:
        if not self.records:
            raise ValueError("The analysis contains no quarterly records.")

        return self.records[-1]

    @property
    def overall_completeness(self) -> float:
        if not self.records:
            return 0.0

        return sum(
            record.completeness
            for record in self.records
        ) / len(self.records)