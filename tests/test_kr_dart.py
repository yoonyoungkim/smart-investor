"""Tests for the Korean DART collectors (step 2).

These cover the parsing and mapping logic with stubbed API payloads; no network
access and no DART key are required.
"""

from datetime import date

import pandas as pd
import pytest

from smart_investor.collectors.kr import accounts
from smart_investor.collectors.kr.dart import DartClient, DartStatus
from smart_investor.collectors.kr.dividend import KRDividendCollector
from smart_investor.collectors.kr.financial import KRFinancialCollector

# Collectors request the most recent *completed* fiscal year, so stub keys and
# expected dates are derived rather than hard-coded to avoid breaking next year.
LATEST_YEAR = date.today().year - 1


def _period(year: int) -> str:
    """Build a DART income-statement period label for a fiscal year."""
    return f"{year}.01.01 ~ {year}.12.31"


@pytest.fixture
def no_api_key(monkeypatch):
    """Guarantee an unconfigured client even when a real .env holds a key.

    DartClient loads .env on construction, so without this the "missing key"
    tests would pick up a developer's real key and call the live API.
    """
    monkeypatch.setattr("smart_investor.collectors.kr.dart.load_env", lambda: None)
    monkeypatch.delenv("DART_API_KEY", raising=False)


class StubClient(DartClient):
    """DART client returning canned payloads instead of calling the API."""

    def __init__(self, responses, corp_codes=None):
        super().__init__(api_key="stub")
        self._responses = responses
        self._corp_codes = corp_codes or {"005930": "00126380"}
        self.calls = []

    def get_json(self, endpoint, **params):
        self.calls.append((endpoint, params))
        key = (endpoint, params.get("bsns_year"), params.get("fs_div"))
        if key in self._responses:
            return self._responses[key]
        fallback = (endpoint, params.get("bsns_year"))
        return self._responses.get(fallback, (DartStatus("013", "no data"), []))

    def corp_code_map(self, refresh=False):
        return self._corp_codes


class TestAccountMapping:
    """Korean accounts translate to the English names metrics query."""

    def test_maps_ifrs_tag(self):
        assert accounts.map_account("ifrs-full_Assets", None) == "Total Assets"

    def test_maps_korean_name(self):
        assert accounts.map_account(None, "자산총계") == "Total Assets"

    def test_ifrs_tag_wins_over_name(self):
        assert accounts.map_account("ifrs-full_Revenue", "자산총계") == "Total Revenue"

    def test_normalizes_whitespace_in_name(self):
        assert accounts.map_account(None, "매출채권 및 기타채권") == "Accounts Receivable"

    def test_unmapped_returns_none(self):
        assert accounts.map_account("ifrs-full_Unknown", "알수없는계정") is None

    def test_operating_income_variants(self):
        assert accounts.map_account("dart_OperatingIncomeLoss", None) == "Operating Income"
        assert accounts.map_account(None, "영업이익(손실)") == "Operating Income"

    def test_debt_components_detected(self):
        assert accounts.is_debt_component(None, "단기차입금") is True
        assert accounts.is_debt_component(None, "장기차입금") is True
        assert accounts.is_debt_component(None, "자산총계") is False

    def test_debt_components_must_come_from_balance_sheet(self):
        """Cash-flow rows repeat borrowing labels as movements, not balances."""
        assert accounts.is_debt_component(None, "단기차입금", "BS") is True
        assert accounts.is_debt_component(None, "단기차입금", "CF") is False

    def test_finance_costs_kept_separate_from_interest_expense(self):
        """금융비용 bundles FX and other charges, so it is not interest expense."""
        assert accounts.map_account(None, "이자비용") == "Interest Expense"
        assert accounts.map_account(None, "금융비용") == "Finance Costs"
        assert accounts.map_account("ifrs-full_FinanceCosts", None) == "Finance Costs"


class TestStatementScoping:
    """The same IFRS tag means different things in different statements."""

    def test_equity_total_read_only_from_balance_sheet(self):
        """ifrs-full_Equity also labels every component row in the SCE."""
        assert accounts.map_account("ifrs-full_Equity", "자본총계", "BS") == "Total Equity"
        assert accounts.map_account("ifrs-full_Equity", "자본총계", "SCE") is None

    def test_cash_not_read_from_cash_flow_statement(self):
        assert accounts.map_account(
            "ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "BS"
        ) == "Cash And Cash Equivalents"
        assert accounts.map_account(
            "ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "CF"
        ) is None

    def test_income_accounts_accept_is_and_cis(self):
        for division in ("IS", "CIS"):
            assert accounts.map_account("ifrs-full_Revenue", "매출액", division) == "Total Revenue"

    def test_income_accounts_rejected_on_balance_sheet(self):
        assert accounts.map_account("ifrs-full_Revenue", "매출액", "BS") is None

    def test_statement_is_optional(self):
        """Omitting the division keeps the mapping unscoped."""
        assert accounts.map_account("ifrs-full_Equity", "자본총계") == "Total Equity"

    def test_unscoped_accounts_pass_any_statement(self):
        """Accounts with no declared statement are not filtered."""
        assert "Total Debt" not in accounts.ACCOUNT_STATEMENTS

    def test_parse_rows_drops_wrong_statement(self):
        collector = KRFinancialCollector(client=StubClient({}))
        sce_row = {
            "sj_div": "SCE",
            "account_id": "ifrs-full_Equity",
            "account_nm": "자본총계",
            "thstrm_amount": "897,514",
            "thstrm_dt": "2025.12.31 현재",
        }
        assert collector._parse_rows([sce_row], "005930", 2025) == []

    def test_parse_rows_keeps_balance_sheet_equity(self):
        collector = KRFinancialCollector(client=StubClient({}))
        bs_row = {
            "sj_div": "BS",
            "account_id": "ifrs-full_Equity",
            "account_nm": "자본총계",
            "thstrm_amount": "436,320",
            "thstrm_dt": "2025.12.31 현재",
        }
        records = collector._parse_rows([bs_row], "005930", 2025)
        assert len(records) == 1
        assert records[0]["account"] == "Total Equity"
        assert records[0]["value"] == 436320.0

    def test_every_metric_account_is_reachable(self):
        """Each account the calculator needs has at least one Korean mapping."""
        required = {
            "Total Revenue",
            "Operating Income",
            "Total Assets",
            "Current Liabilities",
            "Cash And Cash Equivalents",
            "Accounts Receivable",
            "Interest Expense",
        }
        mapped = set(accounts.ACCOUNT_ID_MAP.values()) | set(accounts.ACCOUNT_NAME_MAP.values())
        assert required.issubset(mapped)


class TestAmountParsing:
    """DART amount strings parse into floats."""

    @pytest.mark.parametrize("raw,expected", [
        ("1,234,567", 1234567.0),
        ("-1,234", -1234.0),
        ("0", 0.0),
        ("", None),
        ("-", None),
        (None, None),
        ("n/a", None),
    ])
    def test_parse_amount(self, raw, expected):
        assert KRFinancialCollector._parse_amount(raw) == expected


class TestPeriodParsing:
    """Period labels resolve to the period end date."""

    def test_balance_sheet_label(self):
        assert KRFinancialCollector._parse_period_end("2024.12.31 현재", 2024) == date(2024, 12, 31)

    def test_income_statement_range_uses_end(self):
        result = KRFinancialCollector._parse_period_end("2024.01.01 ~ 2024.12.31", 2024)
        assert result == date(2024, 12, 31)

    def test_non_december_fiscal_year_end(self):
        result = KRFinancialCollector._parse_period_end("2024.04.01 ~ 2025.03.31", 2024)
        assert result == date(2025, 3, 31)

    def test_missing_label_falls_back_to_year_end(self):
        assert KRFinancialCollector._parse_period_end(None, 2022) == date(2022, 12, 31)

    def test_malformed_label_falls_back(self):
        assert KRFinancialCollector._parse_period_end("제55기", 2021) == date(2021, 12, 31)


class TestFinancialParsing:
    """Statement rows become long-format records."""

    def _row(self, **overrides):
        row = {
            "account_id": "ifrs-full_Assets",
            "account_nm": "자산총계",
            "thstrm_amount": "1,000",
            "thstrm_dt": "2024.12.31 현재",
            "frmtrm_amount": "900",
            "frmtrm_dt": "2023.12.31 현재",
            "bfefrmtrm_amount": "800",
            "bfefrmtrm_dt": "2022.12.31 현재",
        }
        row.update(overrides)
        return row

    def test_three_periods_per_row(self):
        collector = KRFinancialCollector(client=StubClient({}))
        records = collector._parse_rows([self._row()], "005930", 2024)

        assert len(records) == 3
        assert {r["date"] for r in records} == {
            date(2024, 12, 31), date(2023, 12, 31), date(2022, 12, 31)
        }
        assert all(r["account"] == "Total Assets" for r in records)
        assert all(r["freq"] == "y" for r in records)
        assert all(r["ticker"] == "005930" for r in records)

    def test_unmapped_accounts_skipped(self):
        collector = KRFinancialCollector(client=StubClient({}))
        records = collector._parse_rows(
            [self._row(account_id="ifrs-full_Nope", account_nm="기타")], "005930", 2024
        )
        assert records == []

    def test_blank_amounts_skipped(self):
        collector = KRFinancialCollector(client=StubClient({}))
        records = collector._parse_rows(
            [self._row(frmtrm_amount="-", bfefrmtrm_amount="")], "005930", 2024
        )
        assert len(records) == 1

    def test_debt_components_become_total_debt(self):
        collector = KRFinancialCollector(client=StubClient({}))
        df = pd.DataFrame([
            {"ticker": "A", "date": date(2024, 12, 31), "account": "__debt__단기차입금",
             "value": 100.0, "freq": "y"},
            {"ticker": "A", "date": date(2024, 12, 31), "account": "__debt__장기차입금",
             "value": 250.0, "freq": "y"},
            {"ticker": "A", "date": date(2024, 12, 31), "account": "Total Assets",
             "value": 1000.0, "freq": "y"},
        ])

        result = collector._add_derived_debt(df)

        assert not result["account"].str.startswith("__debt__").any()
        total_debt = result[result["account"] == "Total Debt"]
        assert len(total_debt) == 1
        assert total_debt.iloc[0]["value"] == 350.0

    def test_no_debt_components_leaves_frame_unchanged(self):
        collector = KRFinancialCollector(client=StubClient({}))
        df = pd.DataFrame([
            {"ticker": "A", "date": date(2024, 12, 31), "account": "Total Assets",
             "value": 1000.0, "freq": "y"},
        ])
        assert collector._add_derived_debt(df).equals(df)


class TestFinancialCollect:
    """End-to-end collection against a stubbed client."""

    def _payload(self):
        return (DartStatus("000", "정상"), [
            {
                "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
                "thstrm_amount": "3,000",
                "thstrm_dt": _period(LATEST_YEAR),
                "frmtrm_amount": "2,500",
                "frmtrm_dt": _period(LATEST_YEAR - 1),
                "bfefrmtrm_amount": "2,000",
                "bfefrmtrm_dt": _period(LATEST_YEAR - 2),
            },
            {
                "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익",
                "thstrm_amount": "300",
                "thstrm_dt": _period(LATEST_YEAR),
                "frmtrm_amount": "250",
                "frmtrm_dt": _period(LATEST_YEAR - 1),
                "bfefrmtrm_amount": "200",
                "bfefrmtrm_dt": _period(LATEST_YEAR - 2),
            },
        ])

    def test_collect_returns_long_format(self):
        responses = {("fnlttSinglAcntAll", str(LATEST_YEAR), "CFS"): self._payload()}
        collector = KRFinancialCollector(client=StubClient(responses), report_years=1)

        result = collector.collect("005930")

        assert result.success is True
        df = result.data
        assert list(df.columns) == ["ticker", "date", "account", "value", "freq"]
        assert set(df["account"]) == {"Total Revenue", "Operating Income"}
        assert len(df) == 6

    def test_falls_back_to_separate_statements(self):
        responses = {
            ("fnlttSinglAcntAll", str(LATEST_YEAR), "CFS"): (DartStatus("013", "no data"), []),
            ("fnlttSinglAcntAll", str(LATEST_YEAR), "OFS"): self._payload(),
        }
        stub = StubClient(responses)
        collector = KRFinancialCollector(client=stub, report_years=1)

        assert collector.collect("005930").success is True
        assert [c[1]["fs_div"] for c in stub.calls] == ["CFS", "OFS"]

    def test_unknown_ticker_reports_clearly(self):
        collector = KRFinancialCollector(client=StubClient({}, corp_codes={}))
        result = collector.collect("999999")

        assert result.success is False
        assert "not registered in DART" in result.error

    def test_quarterly_is_rejected(self):
        collector = KRFinancialCollector(client=StubClient({}))
        result = collector.collect("005930", frequency="quarterly")

        assert result.success is False
        assert "yearly" in result.error

    def test_missing_api_key_reports_clearly(self, no_api_key):
        collector = KRFinancialCollector(client=DartClient(api_key=None))
        result = collector.collect("005930")

        assert result.success is False
        assert "DART_API_KEY" in result.error

    def test_duplicate_periods_are_deduplicated(self):
        # 2025 and 2024 reports both describe fiscal 2024 and 2023.
        responses = {
            ("fnlttSinglAcntAll", str(LATEST_YEAR), "CFS"): self._payload(),
            ("fnlttSinglAcntAll", str(LATEST_YEAR - 1), "CFS"): self._payload(),
        }
        collector = KRFinancialCollector(client=StubClient(responses), report_years=2)

        df = collector.collect("005930").data
        assert not df.duplicated(subset=["ticker", "date", "account"]).any()


class TestDividendCollect:
    """Dividend disclosures become per-year dividend rows."""

    def _payload(self):
        return (DartStatus("000", "정상"), [
            {
                "se": "주당 현금배당금(원)", "stock_knd": "보통주",
                "thstrm": "1,444", "frmtrm": "1,444", "lwfr": "2,994",
            },
            {
                "se": "주당 현금배당금(원)", "stock_knd": "우선주",
                "thstrm": "1,445", "frmtrm": "1,445", "lwfr": "2,995",
            },
            {
                "se": "현금배당수익률(%)", "stock_knd": "보통주",
                "thstrm": "2.5", "frmtrm": "2.1", "lwfr": "1.9",
            },
        ])

    def test_common_stock_only(self):
        responses = {("alotMatter", str(LATEST_YEAR)): self._payload()}
        collector = KRDividendCollector(client=StubClient(responses), report_years=1)

        df = collector.collect("005930").data

        assert len(df) == 3
        assert set(df["Cash Amount"]) == {1444.0, 2994.0}
        assert list(df.columns) == ["ticker", "Ex-Dividend Date", "Cash Amount", "Pay Date"]

    def test_dates_are_fiscal_year_ends(self):
        responses = {("alotMatter", str(LATEST_YEAR)): self._payload()}
        collector = KRDividendCollector(client=StubClient(responses), report_years=1)

        dates = sorted(collector.collect("005930").data["Ex-Dividend Date"].dt.date)
        assert dates == [
            date(LATEST_YEAR - 2, 12, 31),
            date(LATEST_YEAR - 1, 12, 31),
            date(LATEST_YEAR, 12, 31),
        ]

    def test_yield_rows_ignored(self):
        responses = {("alotMatter", str(LATEST_YEAR)): self._payload()}
        collector = KRDividendCollector(client=StubClient(responses), report_years=1)

        assert 2.5 not in set(collector.collect("005930").data["Cash Amount"])

    def test_zero_dividends_dropped(self):
        payload = (DartStatus("000", "정상"), [
            {"se": "주당 현금배당금(원)", "stock_knd": "보통주",
             "thstrm": "0", "frmtrm": "-", "lwfr": "100"},
        ])
        collector = KRDividendCollector(
            client=StubClient({("alotMatter", str(LATEST_YEAR)): payload}), report_years=1
        )

        df = collector.collect("005930").data
        assert len(df) == 1
        assert df.iloc[0]["Cash Amount"] == 100.0

    def test_no_disclosure_reports_clearly(self):
        collector = KRDividendCollector(client=StubClient({}), report_years=1)
        result = collector.collect("005930")

        assert result.success is False
        assert "No dividend data" in result.error

    def test_missing_api_key_reports_clearly(self, no_api_key):
        collector = KRDividendCollector(client=DartClient(api_key=None))
        result = collector.collect("005930")

        assert result.success is False
        assert "DART_API_KEY" in result.error


class TestDartStatus:
    """Status codes decode to the right behaviour."""

    def test_ok(self):
        assert DartStatus("000", "정상").ok is True

    def test_no_data(self):
        status = DartStatus("013", "조회된 데이터가 없습니다")
        assert status.no_data is True
        assert status.ok is False

    def test_rate_limited(self):
        assert DartStatus("020", "요청 제한 초과").rate_limited is True
