"""Build the recommendation report as an Excel workbook.

Slack renders no tables, and an eleven-column screener line wraps unreadably in
a code block. A workbook keeps the columns intact, sorts and filters natively,
and is what the numbers get pasted into anyway.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# (header, key, width, number format). Order matches the requested layout.
_BASE_COLUMNS = (
    ("No.", "no", 5, "0"),
    ("Ticker", "ticker", 10, None),
    ("Company", "company", 30, None),
    ("Sector", "sector", 22, None),
    ("Industry", "industry", 28, None),
    ("Country", "country", 14, None),
    ("Market Cap", "market_cap", 16, "#,##0"),
    ("P/E", "pe_ratio", 9, "0.00"),
    ("Price", "price", 12, "#,##0.00"),
    ("Change", "change", 10, "0.00%"),
    ("Volume", "volume", 14, "#,##0"),
)

# The metrics that decided the sheet's rows are appended to the shared columns,
# so each strategy shows the numbers its own criteria were checked against.
_STRATEGY_COLUMNS = {
    "dividend": (
        ("Div Yield", "dividend_yield", 11, "0.00"),
        ("Div Years", "years_of_dividend", 10, "0"),
        ("Debt Ratio", "debt_ratio", 11, "0.00"),
        ("Quick Ratio", "quick_ratio", 12, "0.00"),
    ),
    "value": (
        # Replaces the shared "P/E" rather than sitting beside it: this is the
        # ratio the criteria were actually tested against - computed from stored
        # statements and corrected against a live market cap during shortlist
        # verification - so showing the market's trailing figure next to it
        # would put two near-identical columns side by side.
        ("PER", "per", 9, "0.00"),
        ("PBR", "pbr", 9, "0.00"),
        ("ROE", "roe", 9, "0.00"),
        ("Op Margin", "operating_margin", 11, "0.00"),
        ("Debt Ratio", "debt_ratio", 11, "0.00"),
    ),
}

# Sheet titles per strategy, used when several strategies share one workbook.
STRATEGY_TITLES = {"dividend": "배당주", "value": "가치주"}


# Shared columns a strategy supersedes with one of its own.
_SUPERSEDED_BASE_COLUMNS = {"value": {"P/E"}}


def columns_for(strategy: str) -> tuple:
    """Return the column layout for a strategy.

    Args:
        strategy: ``dividend`` or ``value``.

    Returns:
        Tuple of (header, key, width, number format).
    """
    superseded = _SUPERSEDED_BASE_COLUMNS.get(strategy, set())
    base = tuple(column for column in _BASE_COLUMNS if column[0] not in superseded)

    return base + _STRATEGY_COLUMNS.get(strategy, _STRATEGY_COLUMNS["dividend"])


_HEADER_FILL = PatternFill("solid", fgColor="1F3864")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_TITLE_FONT = Font(bold=True, size=13)
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def build_workbook(
    rows: list[dict],
    path: str | Path,
    market: str = "ALL",
    total_analyzed: int = 0,
    criteria: list[str] | None = None,
    strategy: str = "dividend",
) -> Path:
    """Write one strategy's recommendation rows to an xlsx file.

    Args:
        rows: One dict per recommended stock, keyed by the column keys above.
        path: Destination file path.
        market: Market label for the title.
        total_analyzed: How many stocks were screened.
        criteria: Descriptions of the active criteria.
        strategy: Which column layout to use.

    Returns:
        The path written.
    """
    return build_multi_workbook(
        [{
            "strategy": strategy,
            "rows": rows,
            "criteria": criteria,
            "total_analyzed": total_analyzed,
        }],
        path,
        market=market,
    )


def build_multi_workbook(
    sheets: list[dict],
    path: str | Path,
    market: str = "ALL",
) -> Path:
    """Write several strategies to one workbook, a sheet each.

    Keeping both strategies in one file means one attachment to open and one
    place to compare them, rather than two files that drift apart.

    Args:
        sheets: One dict per strategy with ``strategy``, ``rows``, ``criteria``
            and ``total_analyzed`` keys.
        path: Destination file path.
        market: Market label for the titles.

    Returns:
        The path written.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)

    for spec in sheets:
        _write_result_sheet(workbook, spec, market)

    _write_criteria_sheet(workbook, sheets, market)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)

    total = sum(len(s["rows"]) for s in sheets)
    logger.info(f"Wrote {total} rows across {len(sheets)} sheet(s) to {destination}")

    return destination


def _write_result_sheet(workbook: Workbook, spec: dict, market: str) -> None:
    """Write one strategy's rows to its own sheet.

    Args:
        workbook: Target workbook.
        spec: Strategy specification.
        market: Market label.
    """
    strategy = spec.get("strategy", "dividend")
    rows = spec.get("rows") or []
    total_analyzed = spec.get("total_analyzed", 0)
    columns = columns_for(strategy)
    title = STRATEGY_TITLES.get(strategy, strategy)

    sheet = workbook.create_sheet(f"{title} {market}")

    sheet.cell(row=1, column=1, value=f"{title} 추천 ({market})").font = _TITLE_FONT
    sheet.cell(
        row=2,
        column=1,
        value=(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}   "
            f"통과 {len(rows)} / {total_analyzed:,}"
        ),
    )

    header_row = 4
    for index, (header, _, width, _fmt) in enumerate(columns, start=1):
        cell = sheet.cell(row=header_row, column=index, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER
        sheet.column_dimensions[get_column_letter(index)].width = width

    for offset, row in enumerate(rows):
        excel_row = header_row + 1 + offset
        for index, (_header, key, _width, number_format) in enumerate(columns, start=1):
            value = row.get(key)
            cell = sheet.cell(row=excel_row, column=index)
            # Leave genuinely unknown fields blank; a 0 would read as a real
            # measurement and sort alongside real ones.
            cell.value = "-" if value is None else value
            cell.border = _BORDER
            if number_format and value is not None:
                cell.number_format = number_format

    # Freeze the header and enable filtering so the sheet is usable as-is.
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    if rows:
        sheet.auto_filter.ref = (
            f"A{header_row}:{get_column_letter(len(columns))}{header_row + len(rows)}"
        )


def _write_criteria_sheet(workbook: Workbook, sheets: list[dict], market: str) -> None:
    """Record every strategy's criteria on one sheet.

    Thresholds are configurable per run, so a list of tickers without them is
    not reproducible.

    Args:
        workbook: Target workbook.
        sheets: The strategy specifications written to this workbook.
        market: Market label.
    """
    sheet = workbook.create_sheet("Criteria")
    sheet.column_dimensions["A"].width = 20
    sheet.column_dimensions["B"].width = 60

    sheet.cell(row=1, column=1, value="적용 조건").font = _TITLE_FONT
    sheet.cell(row=2, column=1, value="생성 시각").font = Font(bold=True)
    sheet.cell(row=2, column=2, value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    sheet.cell(row=3, column=1, value="시장").font = Font(bold=True)
    sheet.cell(row=3, column=2, value=market)

    line = 5
    for spec in sheets:
        strategy = spec.get("strategy", "dividend")
        title = STRATEGY_TITLES.get(strategy, strategy)
        rows = spec.get("rows") or []

        sheet.cell(row=line, column=1, value=f"[{title}]").font = Font(bold=True)
        sheet.cell(
            row=line,
            column=2,
            value=f"통과 {len(rows)} / {spec.get('total_analyzed', 0):,}",
        )
        line += 1

        for item in spec.get("criteria") or ["(전체 조건)"]:
            sheet.cell(row=line, column=2, value=item)
            line += 1

        line += 1
