"""Korean dividend collector using the DART OpenAPI.

pykrx exposes no dividend endpoint, so dividend history is read from DART's
``alotMatter`` disclosure (배당에 관한 사항), which reports the per-share cash
dividend for each fiscal year.

Granularity note: DART discloses an *annual* per-share dividend, not individual
payment events. Each fiscal year therefore produces one row dated at the fiscal
year end, which is also the record date for the year-end dividend that makes up
the bulk of Korean payouts. Metrics that aggregate dividends by year
(yield, growth trend, consecutive years) are unaffected; per-payment analysis is
not possible from this source.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from ..base import CollectionResult, DataCollector
from .dart import REPORT_ANNUAL, DartApiKeyError, DartClient

# ``se`` labels carrying the per-share cash dividend. Whitespace varies between
# filers, so comparison is done on a whitespace-stripped form.
_CASH_DPS_LABELS = {
    "주당현금배당금(원)",
    "주당현금배당금",
}

# ``se`` labels carrying the dividend yield the filer disclosed for the year.
# Collected alongside the per-share amount because the two together reveal the
# share basis: DPS / (yield/100) is the price the filer computed against. When
# that implied price is far from today's market price, the shares were split
# after the fiscal year and the per-share amount is on the old basis.
_CASH_YIELD_LABELS = {
    "현금배당수익률(%)",
    "현금배당수익률",
}

# Indicator name used when the disclosed yield is stored in ``global_value``.
DISCLOSED_YIELD_INDICATOR = "DY_DART"

# Only common shares feed the metrics; preferred shares trade separately.
_COMMON_STOCK_LABELS = {"보통주", "보통주식", ""}

# ``alotMatter`` reports current / prior / two-years-prior figures per report.
_PERIOD_FIELDS = [("thstrm", 0), ("frmtrm", 1), ("lwfr", 2)]


class KRDividendCollector(DataCollector[pd.DataFrame]):
    """Collects Korean dividend history from DART.

    Args:
        client: Pre-built DART client. A default one is created when omitted.
        report_years: How many annual reports to request per company. Three
            reports cover roughly five fiscal years, enough for the
            five-consecutive-years criterion.
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
        self._yields: list[dict[str, Any]] = []

        if not self.client.configured:
            self.logger.warning(
                "DART_API_KEY is not set - Korean dividends cannot be collected. "
                "Register at https://opendart.fss.or.kr/ and set DART_API_KEY in .env"
            )

    def collect(
        self,
        symbol: str,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect dividend history for a Korean stock.

        Args:
            symbol: 6-digit Korean stock code.
            start_date: Drop dividends before this date.
            end_date: Drop dividends after this date.

        Returns:
            CollectionResult with a DataFrame of
            ``ticker, Ex-Dividend Date, Cash Amount, Pay Date``.
        """
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

        records: list[dict[str, Any]] = []
        # Disclosed yields are collected by the same requests and accumulated
        # here; they are returned alongside the amounts rather than as a second
        # pass, which would double the DART request count.
        self._yields = []
        latest_year = date.today().year - 1

        for offset in range(self.report_years):
            business_year = latest_year - offset
            records.extend(self._fetch_year(corp_code, symbol, business_year))

        if not records:
            return CollectionResult.fail(f"No dividend data found for {symbol}")

        df = pd.DataFrame(records)
        df["Ex-Dividend Date"] = pd.to_datetime(df["Ex-Dividend Date"])

        # A fiscal year shows up in several reports; keep one row per year.
        df = df.sort_values("report_year", ascending=False)
        df = df.drop_duplicates(subset=["ticker", "Ex-Dividend Date"], keep="first")
        df = df.drop(columns=["report_year"])

        if start_date:
            df = df[df["Ex-Dividend Date"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["Ex-Dividend Date"] <= pd.to_datetime(end_date)]

        if df.empty:
            return CollectionResult.fail(
                f"No dividend data in specified date range for {symbol}"
            )

        df = df.sort_values("Ex-Dividend Date").reset_index(drop=True)

        return CollectionResult.ok(
            df,
            symbol=symbol,
            rows=len(df),
            total_dividends=df["Cash Amount"].sum(),
            start=df["Ex-Dividend Date"].min(),
            end=df["Ex-Dividend Date"].max(),
            disclosed_yields=self._disclosed_yield_frame(),
        )

    def _fetch_year(
        self,
        corp_code: str,
        symbol: str,
        business_year: int,
    ) -> list[dict[str, Any]]:
        """Fetch the dividend disclosure for one annual report.

        Args:
            corp_code: DART 8-digit company code.
            symbol: Stock code, used for the ``ticker`` column.
            business_year: Fiscal year of the report to request.

        Returns:
            List of dividend record dicts, one per disclosed fiscal year.
        """
        try:
            status, raw_rows = self.client.get_json(
                "alotMatter",
                corp_code=corp_code,
                bsns_year=str(business_year),
                reprt_code=REPORT_ANNUAL,
            )
        except Exception as exc:
            self.logger.warning(f"{symbol} {business_year}: DART request failed: {exc}")
            return []

        if status.no_data:
            return []
        if not status.ok:
            self.logger.warning(
                f"{symbol} {business_year}: {status.code} {status.message}"
            )
            return []

        records: list[dict[str, Any]] = []

        for raw in raw_rows:
            label = "".join(str(raw.get("se", "")).split())
            is_amount = label in _CASH_DPS_LABELS
            is_yield = label in _CASH_YIELD_LABELS

            if not is_amount and not is_yield:
                continue

            stock_kind = "".join(str(raw.get("stock_knd", "")).split())
            if stock_kind not in _COMMON_STOCK_LABELS:
                continue

            for field, years_back in _PERIOD_FIELDS:
                value = self._parse_amount(raw.get(field))
                if value is None or value <= 0:
                    continue

                fiscal_year = business_year - years_back
                period_end = date(fiscal_year, 12, 31)

                if is_yield:
                    self._yields.append({
                        "ticker": symbol,
                        "date": period_end,
                        "indicator": DISCLOSED_YIELD_INDICATOR,
                        "value": value,
                        "report_year": business_year,
                    })
                    continue

                records.append({
                    "ticker": symbol,
                    "Ex-Dividend Date": period_end,
                    "Cash Amount": value,
                    # DART does not disclose the payment date here; Korean
                    # year-end dividends are paid within ~3 months of the record
                    # date, but recording an invented date would be worse than
                    # leaving it unset.
                    "Pay Date": None,
                    "report_year": business_year,
                })

        return records

    def _disclosed_yield_frame(self) -> pd.DataFrame:
        """Return the disclosed yields gathered during the last collect().

        Returns:
            DataFrame of ``ticker, date, indicator, value`` ready for
            ``global_value``. Empty when the filer disclosed no yield.
        """
        if not self._yields:
            return pd.DataFrame(columns=["ticker", "date", "indicator", "value"])

        df = pd.DataFrame(self._yields)
        # A fiscal year appears in several reports; keep the most recent filing.
        df = df.sort_values("report_year", ascending=False)
        df = df.drop_duplicates(subset=["ticker", "date", "indicator"], keep="first")
        return df.drop(columns=["report_year"]).reset_index(drop=True)

    @staticmethod
    def _parse_amount(raw: Any) -> float | None:
        """Parse a DART amount string such as ``"1,444"``.

        Args:
            raw: Raw amount field.

        Returns:
            Parsed float, or None when blank or non-numeric.
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

    def collect_batch(
        self,
        symbols: list[str],
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> dict[str, CollectionResult[pd.DataFrame]]:
        """Collect dividend data for multiple Korean stocks.

        Args:
            symbols: List of 6-digit stock codes.
            start_date: Drop dividends before this date.
            end_date: Drop dividends after this date.

        Returns:
            Mapping of symbol to its CollectionResult.
        """
        results = {}

        for symbol in symbols:
            self.logger.info(f"Collecting dividends for {symbol}")
            results[symbol] = self.collect_safe(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )

        return results

    def get_dividend_summary(self, symbol: str, years: int = 5) -> dict[str, Any]:
        """Summarise dividend history for a Korean stock.

        Args:
            symbol: 6-digit stock code.
            years: Number of years to look back.

        Returns:
            Dictionary of dividend statistics.
        """
        start_date = datetime.now().replace(year=datetime.now().year - years)
        result = self.collect(symbol=symbol, start_date=start_date)

        if not result.success or result.data is None:
            return {
                "symbol": symbol,
                "has_dividends": False,
                "error": result.error,
            }

        df = result.data
        yearly = df.groupby(df["Ex-Dividend Date"].dt.year)["Cash Amount"].sum()

        return {
            "symbol": symbol,
            "has_dividends": True,
            "years_of_data": len(yearly),
            "total_payments": len(df),
            "avg_annual_dividend": yearly.mean(),
            "latest_dividend": df.iloc[-1]["Cash Amount"] if len(df) > 0 else 0,
            "total_dividend": df["Cash Amount"].sum(),
            "yearly_dividends": yearly.to_dict(),
        }
