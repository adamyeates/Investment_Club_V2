from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from .models import CompanyInfo, QuarterRecord
from .sec_client import SecClient, SecCompanyPayload


@dataclass(frozen=True)
class FactValue:
    value: float
    end: date
    start: date | None
    filed: date | None
    accession: str
    form: str
    concept: str
    fy: int | None = None
    fp: str = ""

    @property
    def duration_days(self) -> int | None:
        if self.start is None:
            return None

        return (self.end - self.start).days + 1


DURATION_METRICS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": (
        "NetIncomeLoss",
        "ProfitLoss",
    ),
    "diluted_eps": ("EarningsPerShareDiluted",),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
    ),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
    "interest_expense": (
        "InterestExpenseNonOperating",
        "InterestAndDebtExpense",
        "InterestExpense",
    ),
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    ),
    "dividends_paid": (
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
    ),
    "share_repurchases": (
        "PaymentsForRepurchaseOfCommonStock",
    ),
}


INSTANT_METRICS: dict[
    str,
    tuple[tuple[str, str], ...],
] = {
    "cash": (
        ("us-gaap", "CashAndShortTermInvestments"),
        (
            "us-gaap",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        (
            "us-gaap",
            "CashAndCashEquivalentsAtCarryingValue",
        ),
    ),
    "accounts_receivable": (
        ("us-gaap", "AccountsReceivableNetCurrent"),
        (
            "us-gaap",
            "AccountsNotesAndLoansReceivableNetCurrent",
        ),
    ),
    "inventory": (
        ("us-gaap", "InventoryNet"),
    ),
    "current_assets": (
        ("us-gaap", "AssetsCurrent"),
    ),
    "current_liabilities": (
        ("us-gaap", "LiabilitiesCurrent"),
    ),
    "total_assets": (
        ("us-gaap", "Assets"),
    ),
    "total_liabilities": (
        ("us-gaap", "Liabilities"),
    ),
    "shareholders_equity": (
        ("us-gaap", "StockholdersEquity"),
        (
            "us-gaap",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
    ),
    "shares_outstanding": (
        ("dei", "EntityCommonStockSharesOutstanding"),
    ),
}


def normalize_sec_company(
    payload: SecCompanyPayload,
    quarter_limit: int = 20,
) -> tuple[
    CompanyInfo,
    list[QuarterRecord],
    list[str],
]:
    facts = payload.company_facts.get("facts", {})
    filing_index = SecClient.filing_index(payload.submissions)
    warnings: list[str] = []

    duration_maps: dict[
        str,
        dict[tuple[int, int], FactValue],
    ] = {}

    for metric, tags in DURATION_METRICS.items():
        unit = (
            "USD/shares"
            if metric == "diluted_eps"
            else "USD"
        )

        duration_maps[metric] = first_duration_map(
            facts,
            "us-gaap",
            tags,
            unit,
        )

    instant_maps: dict[
        str,
        dict[tuple[int, int], FactValue],
    ] = {}

    for metric, concepts in INSTANT_METRICS.items():
        unit = (
            "shares"
            if metric == "shares_outstanding"
            else "USD"
        )

        instant_maps[metric] = first_instant_map(
            facts,
            concepts,
            unit,
        )

    instant_maps["total_debt"] = build_total_debt(facts)

    keys: set[tuple[int, int]] = set()

    for values in [
        *duration_maps.values(),
        *instant_maps.values(),
    ]:
        keys.update(values.keys())

    records: list[QuarterRecord] = []

    for fiscal_year, fiscal_quarter in keys:
        if fiscal_quarter not in (1, 2, 3, 4):
            continue

        candidates = [
            values.get((fiscal_year, fiscal_quarter))
            for values in [
                *duration_maps.values(),
                *instant_maps.values(),
            ]
        ]

        available = [
            value
            for value in candidates
            if value is not None
        ]

        if not available:
            continue

        period_fact = max(
            available,
            key=lambda value: value.end,
        )

        metadata_fact = best_metadata_fact(available)

        filing = filing_index.get(
            metadata_fact.accession,
            {},
        )

        primary_document = filing.get(
            "primary_document",
            "",
        )

        source_url = SecClient.filing_url(
            payload.cik,
            metadata_fact.accession,
            primary_document,
        )

        record = QuarterRecord(
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            period_end=period_fact.end,
            form=metadata_fact.form,
            filed_date=metadata_fact.filed,
            accession=metadata_fact.accession,
            sec_source_url=source_url,
        )

        for metric, values in duration_maps.items():
            value = values.get(
                (fiscal_year, fiscal_quarter)
            )

            if value is not None:
                setattr(record, metric, value.value)

        for metric, values in instant_maps.items():
            value = values.get(
                (fiscal_year, fiscal_quarter)
            )

            if value is not None:
                setattr(record, metric, value.value)

        for positive_metric in (
            "capital_expenditures",
            "interest_expense",
            "dividends_paid",
            "share_repurchases",
        ):
            value = getattr(record, positive_metric)

            if value is not None:
                setattr(
                    record,
                    positive_metric,
                    abs(value),
                )

        record.completeness = record_completeness(record)

        if (
            record.revenue is not None
            or record.total_assets is not None
        ):
            records.append(record)

    by_end: dict[date, QuarterRecord] = {}

    for record in records:
        current = by_end.get(record.period_end)

        if (
            current is None
            or record.completeness > current.completeness
        ):
            by_end[record.period_end] = record

    records = sorted(
        by_end.values(),
        key=lambda value: value.period_end,
    )[-quarter_limit:]

    if not records:
        warnings.append(
            "No comparable quarterly SEC XBRL facts were found."
        )

    elif records[-1].completeness < 0.55:
        warnings.append(
            "The latest filing has limited standardized-tag coverage. "
            "Review the source filing."
        )

    entity_name = str(
        payload.company_facts.get("entityName")
        or payload.submissions.get("name")
        or payload.ticker
    )

    company = CompanyInfo(
        ticker=payload.ticker,
        company_name=entity_name,
        cik=f"{payload.cik:010d}",
    )

    return company, records, warnings


def first_duration_map(
    facts: dict[str, Any],
    namespace: str,
    tags: Iterable[str],
    preferred_unit: str,
) -> dict[tuple[int, int], FactValue]:
    combined: dict[
        tuple[int, int],
        FactValue,
    ] = {}

    for tag in tags:
        rows = concept_rows(
            facts,
            namespace,
            tag,
            preferred_unit,
        )

        current = discrete_duration_map(rows)

        for key, value in current.items():
            combined.setdefault(key, value)

    return combined


def first_instant_map(
    facts: dict[str, Any],
    concepts: Iterable[tuple[str, str]],
    preferred_unit: str,
) -> dict[tuple[int, int], FactValue]:
    combined: dict[
        tuple[int, int],
        FactValue,
    ] = {}

    for namespace, tag in concepts:
        rows = concept_rows(
            facts,
            namespace,
            tag,
            preferred_unit,
        )

        current = instant_map(rows)

        for key, value in current.items():
            combined.setdefault(key, value)

    return combined


def concept_rows(
    facts: dict[str, Any],
    namespace: str,
    concept: str,
    preferred_unit: str,
) -> list[FactValue]:
    concept_data = (
        facts
        .get(namespace, {})
        .get(concept, {})
    )

    units = concept_data.get("units", {})
    selected = units.get(preferred_unit, [])

    rows: list[FactValue] = []

    for item in selected or []:
        if item.get("form") not in {
            "10-Q",
            "10-Q/A",
            "10-K",
            "10-K/A",
        }:
            continue

        try:
            value = float(item["val"])
            end = date.fromisoformat(item["end"])

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        rows.append(
            FactValue(
                value=value,
                end=end,
                start=date_or_none(item.get("start")),
                filed=date_or_none(item.get("filed")),
                accession=str(item.get("accn", "")),
                form=str(item.get("form", "")),
                concept=concept,
                fy=int_or_none(item.get("fy")),
                fp=str(item.get("fp", "")),
            )
        )

    return rows


def instant_map(
    rows: list[FactValue],
) -> dict[tuple[int, int], FactValue]:
    grouped: dict[
        tuple[int, int],
        list[FactValue],
    ] = {}

    for row in rows:
        fiscal_year = row.fy
        quarter = quarter_number(row.fp)

        if fiscal_year is None or quarter is None:
            continue

        grouped.setdefault(
            (fiscal_year, quarter),
            [],
        ).append(row)

    result: dict[
        tuple[int, int],
        FactValue,
    ] = {}

    for key, candidates in grouped.items():
        latest_end = max(
            item.end
            for item in candidates
        )

        same_end = [
            item
            for item in candidates
            if item.end == latest_end
        ]

        result[key] = max(
            same_end,
            key=filed_sort_key,
        )

    return result


def discrete_duration_map(
    rows: list[FactValue],
) -> dict[tuple[int, int], FactValue]:
    grouped: dict[
        tuple[int, int],
        list[FactValue],
    ] = {}

    for row in rows:
        fiscal_year = row.fy
        quarter = quarter_number(row.fp)

        if (
            fiscal_year is None
            or quarter is None
            or row.start is None
        ):
            continue

        grouped.setdefault(
            (fiscal_year, quarter),
            [],
        ).append(row)

    direct: dict[
        tuple[int, int],
        FactValue,
    ] = {}

    cumulative: dict[
        tuple[int, int],
        FactValue,
    ] = {}

    annual: dict[
        tuple[int, int],
        FactValue,
    ] = {}

    for key, candidates in grouped.items():
        latest_end = max(
            item.end
            for item in candidates
        )

        same_end = [
            item
            for item in candidates
            if item.end == latest_end
        ]

        short = [
            item
            for item in same_end
            if item.duration_days
            and 55 <= item.duration_days <= 125
        ]

        long = [
            item
            for item in same_end
            if item.duration_days
            and 126 <= item.duration_days <= 310
        ]

        year = [
            item
            for item in same_end
            if item.duration_days
            and 311 <= item.duration_days <= 410
        ]

        if short:
            direct[key] = max(
                short,
                key=filed_sort_key,
            )

        if long:
            cumulative[key] = max(
                long,
                key=filed_sort_key,
            )

        if year:
            annual[key] = max(
                year,
                key=filed_sort_key,
            )

    result: dict[
        tuple[int, int],
        FactValue,
    ] = {}

    years = sorted(
        {key[0] for key in grouped}
    )

    for fiscal_year in years:
        for quarter in (1, 2, 3):
            key = (fiscal_year, quarter)

            if key in direct:
                result[key] = direct[key]
                continue

            if key in cumulative:
                previous = [
                    result.get((fiscal_year, q))
                    for q in range(1, quarter)
                ]

                if all(
                    value is not None
                    for value in previous
                ):
                    base = cumulative[key]

                    result[key] = FactValue(
                        value=(
                            base.value
                            - sum(
                                value.value
                                for value in previous
                                if value
                            )
                        ),
                        end=base.end,
                        start=base.start,
                        filed=base.filed,
                        accession=base.accession,
                        form=base.form,
                        concept=base.concept,
                        fy=base.fy,
                        fp=base.fp,
                    )

        annual_key = (fiscal_year, 4)

        annual_fact = (
            annual.get(annual_key)
            or cumulative.get(annual_key)
        )

        previous = [
            result.get((fiscal_year, q))
            for q in (1, 2, 3)
        ]

        if (
            annual_fact is not None
            and all(
                value is not None
                for value in previous
            )
        ):
            result[annual_key] = FactValue(
                value=(
                    annual_fact.value
                    - sum(
                        value.value
                        for value in previous
                        if value
                    )
                ),
                end=annual_fact.end,
                start=annual_fact.start,
                filed=annual_fact.filed,
                accession=annual_fact.accession,
                form=annual_fact.form,
                concept=annual_fact.concept,
                fy=annual_fact.fy,
                fp=annual_fact.fp,
            )

        elif annual_key in direct:
            result[annual_key] = direct[annual_key]

    return result


def build_total_debt(
    facts: dict[str, Any],
) -> dict[tuple[int, int], FactValue]:
    direct = first_instant_map(
        facts,
        (
            (
                "us-gaap",
                "LongTermDebtAndFinanceLeaseObligations",
            ),
            (
                "us-gaap",
                "LongTermDebt",
            ),
        ),
        "USD",
    )

    current = first_instant_map(
        facts,
        (
            (
                "us-gaap",
                "LongTermDebtAndFinanceLeaseObligationsCurrent",
            ),
            (
                "us-gaap",
                "LongTermDebtCurrent",
            ),
            (
                "us-gaap",
                "ShortTermBorrowings",
            ),
        ),
        "USD",
    )

    noncurrent = first_instant_map(
        facts,
        (
            (
                "us-gaap",
                "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            ),
            (
                "us-gaap",
                "LongTermDebtNoncurrent",
            ),
        ),
        "USD",
    )

    result = dict(direct)

    for key in current.keys() | noncurrent.keys():
        current_value = current.get(key)
        noncurrent_value = noncurrent.get(key)

        values = [
            value
            for value in (
                current_value,
                noncurrent_value,
            )
            if value
        ]

        if not values:
            continue

        if (
            key in direct
            and not (
                current_value
                and noncurrent_value
            )
        ):
            continue

        reference = max(
            values,
            key=lambda value: value.end,
        )

        result[key] = FactValue(
            value=sum(
                value.value
                for value in values
            ),
            end=reference.end,
            start=None,
            filed=reference.filed,
            accession=reference.accession,
            form=reference.form,
            concept="CalculatedTotalDebt",
            fy=reference.fy,
            fp=reference.fp,
        )

    return result


def best_metadata_fact(
    facts: list[FactValue],
) -> FactValue:
    return max(
        facts,
        key=lambda value: (
            value.filed or date.min,
            1 if value.form.startswith("10-K") else 0,
            value.end,
        ),
    )


def record_completeness(
    record: QuarterRecord,
) -> float:
    core_fields = (
        "revenue",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "cash",
        "current_assets",
        "current_liabilities",
        "total_assets",
        "total_debt",
        "total_liabilities",
        "shareholders_equity",
        "shares_outstanding",
    )

    populated = sum(
        getattr(record, field) is not None
        for field in core_fields
    )

    return populated / len(core_fields)


def quarter_number(
    fiscal_period: str,
) -> int | None:
    return {
        "Q1": 1,
        "Q2": 2,
        "Q3": 3,
        "FY": 4,
        "Q4": 4,
    }.get(fiscal_period.upper())


def filed_sort_key(
    value: FactValue,
) -> tuple[date, int]:
    return (
        value.filed or date.min,
        1 if value.form.endswith("/A") else 0,
    )


def date_or_none(
    value: Any,
) -> date | None:
    try:
        return date.fromisoformat(str(value))

    except (TypeError, ValueError):
        return None


def int_or_none(
    value: Any,
) -> int | None:
    try:
        return int(value)

    except (TypeError, ValueError):
        return None