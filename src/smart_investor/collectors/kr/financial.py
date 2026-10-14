"""Korean financial statement collector using the DART OpenAPI.

Neither pykrx nor FinanceDataReader exposes Korean financial statements, so this
collector reads them from DART's ``fnlttSinglAcntAll`` endpoint and writes them
into ``global_fs`` under the same English account names the US collector uses.
That keeps :class:`~smart_investor.analysis.calculator.MetricsCalculator` market
agnostic.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

import pandas as pd

from ..base import CollectionResult, DataCollector
from . import accounts
from .dart import (
    FS_CONSOLIDATED,
    FS_SEPARATE,
    REPORT_ANNUAL,
    DartApiKeyError,
    DartClient,
)

FrequencyType = Literal["yearly", "quarterly"]

# Each annual report carries the current year plus the two prior years, so
# fetching N report-years yields up to N+2 distinct fiscal years.
_PERIOD_FIELDS = [
    ("thstrm_amount", "thstrm_dt", 0),
    ("frmtrm_amount", "frmtrm_dt", 1),
    ("bfefrmtrm_amount", "bfefrmtrm_dt", 2),
]

_DATE_PATTERN = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")


class KRFinancialCollector(DataCollector[pd.DataFrame]):
    """Collects Korean financial statements from DART.

    Args:
        client: Pre-built DART client. A default one is created when omitted.
        report_years: How many annual reports to request per company. Three
            reports cover roughly five fiscal years, which is what the trend
            filters need.
        delay: Seconds between DART requests.
    """

    def __init__(
        self,
        client: DartClient | None = None,
        report_years: int = 3,
        delay: float = 0.0,
    ) -> None:
        super().__init__()
        self.client = client or DartClient(delay=delay)
        self.report_years = report_years

        if not self.client.configured:
            self.logger.warning(
                "DART_API_KEY is not set - Korean financial statements cannot be "
                "collected. Register at https://opendart.fss.or.kr/ and set "
                "DART_API_KEY in .env"
            )

    def collect(
        self,
        symbol: str,
        frequency: FrequencyType = "yearly",
        after_date: pd.Timestamp | None = None,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect financial statements for a Korean stock.

        Args:
            symbol: 6-digit Korean stock code.
            frequency: Only ``yearly`` is supported; DART annual reports are the
                only source of full-year figures.
            after_date: Skip periods on or before this date.

        Returns:
            CollectionResult with a long-format DataFrame of
            ``ticker, date, account, value, freq``.
        """
        if frequency != "yearly":
            return CollectionResult.fail(
                "KRFinancialCollector supports yearly frequency only "
                "(DART annual reports)"
            )

        try:
            # Checked before the corp_code lookup: that lookup can be served from
            # the on-disk cache without a key, which would otherwise hide the
            # real problem behind a confusing "no data" message.
            self.client.require_key()
            corp_code = self.client.corp_code(symbol)
        except DartApiKeyError as exc:
            return CollectionResult.fail(str(exc))

        if not corp_code:
            return CollectionResult.fail(f"{symbol} is not registered in DART")

        rows: list[dict[str, Any]] = []
        latest_year = date.today().year - 1

        for offset in range(self.report_years):
            business_year = latest_year - offset
            fetched = self._fetch_year(corp_code, symbol, business_year)
            if fetched:
                rows.extend(fetched)

        if not rows:
            return CollectionResult.fail(f"No DART financial data found for {symbol}")

        df = pd.DataFrame(rows)

        # The same fiscal year appears in several reports (as 당기/전기/전전기).
        # Keep one row per period and account, preferring the most recent report.
        df = df.sort_values("report_year", ascending=False)
        df = df.drop_duplicates(subset=["ticker", "date", "account", "freq"], keep="first")
        df = df.drop(columns=["report_year"])

        df = self._add_derived_debt(df)

        if after_date is not None:
            df = df[pd.to_datetime(df["date"]) > after_date]

        if df.empty:
            return CollectionResult.fail(f"No new financial data for {symbol}")

        df = df.sort_values(["date", "account"]).reset_index(drop=True)

        return CollectionResult.ok(
            df,
            symbol=symbol,
            frequency=frequency,
            rows=len(df),
            accounts=df["account"].nunique(),
            periods=df["date"].nunique(),
        )

    def _fetch_year(
        self,
        corp_code: str,
        symbol: str,
        business_year: int,
    ) -> list[dict[str, Any]]:
        """Fetch one annual report, falling back to separate statements.

        Args:
            corp_code: DART 8-digit company code.
            symbol: Stock code, used for the ``ticker`` column.
            business_year: Fiscal year of the report to request.

        Returns:
            List of long-format record dicts. Empty when nothing was disclosed.
        """
        for fs_div in (FS_CONSOLIDATED, FS_SEPARATE):
            try:
                status, raw_rows = self.client.get_json(
                    "fnlttSinglAcntAll",
                    corp_code=corp_code,
                    bsns_year=str(business_year),
                    reprt_code=REPORT_ANNUAL,
                    fs_div=fs_div,
                )
            except Exception as exc:
                self.logger.warning(
                    f"{symbol} {business_year} {fs_div}: DART request failed: {exc}"
                )
                return []

            if status.no_data:
                # Company files no consolidated report; try separate statements.
                continue
            if not status.ok:
                self.logger.warning(
                    f"{symbol} {business_year} {fs_div}: {status.code} {status.message}"
                )
                continue

            parsed = self._parse_rows(raw_rows, symbol, business_year)
            if parsed:
                return parsed

        return []

    def _parse_rows(
        self,
        raw_rows: list[dict[str, Any]],
        symbol: str,
        business_year: int,
    ) -> list[dict[str, Any]]:
        """Convert DART statement rows into long-format records.

        Args:
            raw_rows: ``list`` payload from ``fnlttSinglAcntAll``.
            symbol: Stock code.
            business_year: Fiscal year the report covers.

        Returns:
            List of record dicts ready for ``global_fs``.
        """
        records: list[dict[str, Any]] = []

        for raw in raw_rows:
            account_id = raw.get("account_id")
            account_nm = raw.get("account_nm")
            statement = raw.get("sj_div")

            mapped = accounts.map_account(account_id, account_nm, statement)
            debt_component = accounts.is_debt_component(account_id, account_nm, statement)

            if not mapped and not debt_component:
                continue

            for amount_field, date_field, years_back in _PERIOD_FIELDS:
                value = self._parse_amount(raw.get(amount_field))
                if value is None:
                    continue

                period = self._parse_period_end(
                    raw.get(date_field), business_year - years_back
                )

                if mapped:
                    records.append({
                        "ticker": symbol,
                        "date": period,
                        "account": mapped,
                        "value": value,
                        "freq": "y",
                        "report_year": business_year,
                    })

                if debt_component:
                    # Kept under a private account name so the derived Total Debt
                    # can be summed without polluting the stored account set.
                    records.append({
                        "ticker": symbol,
                        "date": period,
                        "account": f"__debt__{accounts.normalize_name(account_nm)}",
                        "value": value,
                        "freq": "y",
                        "report_year": business_year,
                    })

        return records

    def _add_derived_debt(self, df: pd.DataFrame) -> pd.DataFrame:
        """Sum borrowing line items into a ``Total Debt`` row per period.

        DART discloses short-term and long-term borrowings separately, while the
        debt-ratio metric expects a single ``Total Debt`` figure comparable to
        yfinance's. Periods with no borrowings disclosed get no row, and the
        calculator falls back to total liabilities.

        Args:
            df: Parsed statement rows including private ``__debt__`` accounts.

        Returns:
            DataFrame with ``__debt__`` rows replaced by ``Total Debt`` rows.
        """
        is_component = df["account"].str.startswith("__debt__")
        components = df[is_component]
        result = df[~is_component]

        if components.empty:
            return result

        totals = (
            components.groupby(["ticker", "date", "freq"], as_index=False)["value"]
            .sum()
            .assign(account=accounts.TOTAL_DEBT)
        )

        return pd.concat([result, totals[result.columns]], ignore_index=True)

    @staticmethod
    def _parse_amount(raw: Any) -> float | None:
        """Parse a DART amount string such as ``"-1,234,000"``.

        Args:
            raw: Raw amount field.

        Returns:
            Parsed float, or None when the field is blank or non-numeric.
        """
        if raw is None:
            return None

        text = str(raw).strip().replace(",", "")
        if not text or text == "-":
            return None

        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_period_end(raw: Any, fallback_year: int) -> date:
        """Extract the period-end date from a DART period label.

        Balance-sheet labels read ``2024.12.31 현재`` and income-statement labels
        read ``2024.01.01 ~ 2024.12.31``; in both cases the last date in the
        string is the period end. Falls back to 31 December of the fiscal year
        when the label is missing or malformed.

        Args:
            raw: Raw ``*_dt`` field from DART.
            fallback_year: Fiscal year to assume when parsing fails.

        Returns:
            Period end date.
        """
        if raw:
            matches = _DATE_PATTERN.findall(str(raw))
            if matches:
                year, month, day = matches[-1]
                try:
                    return date(int(year), int(month), int(day))
                except ValueError:
                    pass

        return date(fallback_year, 12, 31)

    def collect_batch(
        self,
        symbols: list[str],
        frequency: FrequencyType = "yearly",
    ) -> dict[str, CollectionResult[pd.DataFrame]]:
        """Collect financial data for multiple Korean stocks.

        Args:
            symbols: List of 6-digit stock codes.
            frequency: Only ``yearly`` is supported.

        Returns:
            Mapping of symbol to its CollectionResult.
        """
        results = {}

        for symbol in symbols:
            self.logger.info(f"Collecting financials for {symbol}")
            results[symbol] = self.collect_safe(symbol=symbol, frequency=frequency)

        return results
