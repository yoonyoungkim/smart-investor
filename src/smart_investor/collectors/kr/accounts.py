"""Mapping from DART/IFRS account identifiers to the project's account names.

Korean filings label accounts with IFRS tags (``account_id``) and Korean names
(``account_nm``); US filings from yfinance use English names. Both land in the
same ``global_fs.account`` column, so Korean accounts are translated here to the
exact English names ``MetricsCalculator`` queries. Without this translation the
Korean rows exist but no metric can find them.
"""

from __future__ import annotations

# Account names the metrics layer looks up. Keep in sync with MetricsCalculator.
TOTAL_REVENUE = "Total Revenue"
OPERATING_INCOME = "Operating Income"
TOTAL_ASSETS = "Total Assets"
TOTAL_DEBT = "Total Debt"
TOTAL_LIABILITIES = "Total Liabilities"
CURRENT_LIABILITIES = "Current Liabilities"
CURRENT_ASSETS = "Current Assets"
CASH_AND_EQUIVALENTS = "Cash And Cash Equivalents"
ACCOUNTS_RECEIVABLE = "Accounts Receivable"
INTEREST_EXPENSE = "Interest Expense"
FINANCE_COSTS = "Finance Costs"
EBIT = "EBIT"
NET_INCOME = "Net Income"
TOTAL_EQUITY = "Total Equity"

# DART statement divisions (``sj_div``).
BALANCE_SHEET = "BS"
INCOME_STATEMENT = "IS"
COMPREHENSIVE_INCOME = "CIS"
CASH_FLOW = "CF"
CHANGES_IN_EQUITY = "SCE"

# Which statement each account may be read from. The same IFRS tag appears in
# several statements - ``ifrs-full_Equity`` labels both 자본총계 on the balance
# sheet and every equity *component* row in the statement of changes in equity,
# and ``ifrs-full_CashAndCashEquivalents`` appears in the cash flow statement as
# a period-end balance. Reading an account from the wrong statement silently
# yields a component or a restated figure instead of the total.
_BALANCE_ONLY = frozenset({BALANCE_SHEET})
_INCOME_ONLY = frozenset({INCOME_STATEMENT, COMPREHENSIVE_INCOME})

ACCOUNT_STATEMENTS: dict[str, frozenset[str]] = {
    TOTAL_ASSETS: _BALANCE_ONLY,
    CURRENT_ASSETS: _BALANCE_ONLY,
    TOTAL_LIABILITIES: _BALANCE_ONLY,
    CURRENT_LIABILITIES: _BALANCE_ONLY,
    CASH_AND_EQUIVALENTS: _BALANCE_ONLY,
    ACCOUNTS_RECEIVABLE: _BALANCE_ONLY,
    TOTAL_EQUITY: _BALANCE_ONLY,
    TOTAL_REVENUE: _INCOME_ONLY,
    OPERATING_INCOME: _INCOME_ONLY,
    NET_INCOME: _INCOME_ONLY,
    INTEREST_EXPENSE: _INCOME_ONLY,
    FINANCE_COSTS: _INCOME_ONLY,
}

# IFRS standard tags are checked first because they are stable across filers,
# unlike the free-text Korean names.
ACCOUNT_ID_MAP: dict[str, str] = {
    "ifrs-full_Revenue": TOTAL_REVENUE,
    "ifrs_Revenue": TOTAL_REVENUE,
    "ifrs-full_RevenueFromContractsWithCustomers": TOTAL_REVENUE,
    "dart_OperatingIncomeLoss": OPERATING_INCOME,
    "ifrs-full_ProfitLossFromOperatingActivities": OPERATING_INCOME,
    "ifrs-full_Assets": TOTAL_ASSETS,
    "ifrs_Assets": TOTAL_ASSETS,
    "ifrs-full_CurrentAssets": CURRENT_ASSETS,
    "ifrs_CurrentAssets": CURRENT_ASSETS,
    "ifrs-full_Liabilities": TOTAL_LIABILITIES,
    "ifrs_Liabilities": TOTAL_LIABILITIES,
    "ifrs-full_CurrentLiabilities": CURRENT_LIABILITIES,
    "ifrs_CurrentLiabilities": CURRENT_LIABILITIES,
    "ifrs-full_CashAndCashEquivalents": CASH_AND_EQUIVALENTS,
    "ifrs_CashAndCashEquivalents": CASH_AND_EQUIVALENTS,
    "dart_CashAndCashEquivalentsAtEndOfPeriodIncludingCashAndCashEquivalents": CASH_AND_EQUIVALENTS,
    "ifrs-full_TradeAndOtherCurrentReceivables": ACCOUNTS_RECEIVABLE,
    "ifrs_TradeAndOtherCurrentReceivables": ACCOUNTS_RECEIVABLE,
    "ifrs-full_CurrentTradeReceivables": ACCOUNTS_RECEIVABLE,
    "ifrs-full_InterestExpense": INTEREST_EXPENSE,
    "ifrs_InterestExpense": INTEREST_EXPENSE,
    # 금융비용 aggregates interest with FX and other finance costs, so it is kept
    # separate and used only as a fallback when true interest expense is absent.
    "ifrs-full_FinanceCosts": FINANCE_COSTS,
    "ifrs_FinanceCosts": FINANCE_COSTS,
    "ifrs-full_ProfitLoss": NET_INCOME,
    "ifrs_ProfitLoss": NET_INCOME,
    "ifrs-full_Equity": TOTAL_EQUITY,
    "ifrs_Equity": TOTAL_EQUITY,
}

# Korean names, used when a filer omits or customises the IFRS tag. Names are
# normalised (whitespace stripped) before lookup.
ACCOUNT_NAME_MAP: dict[str, str] = {
    "매출액": TOTAL_REVENUE,
    "수익(매출액)": TOTAL_REVENUE,
    "수익": TOTAL_REVENUE,
    "영업수익": TOTAL_REVENUE,
    "매출": TOTAL_REVENUE,
    "영업이익": OPERATING_INCOME,
    "영업이익(손실)": OPERATING_INCOME,
    "영업손익": OPERATING_INCOME,
    "자산총계": TOTAL_ASSETS,
    "유동자산": CURRENT_ASSETS,
    "부채총계": TOTAL_LIABILITIES,
    "유동부채": CURRENT_LIABILITIES,
    "현금및현금성자산": CASH_AND_EQUIVALENTS,
    "매출채권": ACCOUNTS_RECEIVABLE,
    "매출채권및기타유동채권": ACCOUNTS_RECEIVABLE,
    "매출채권및기타채권": ACCOUNTS_RECEIVABLE,
    "이자비용": INTEREST_EXPENSE,
    "금융비용": FINANCE_COSTS,
    "당기순이익": NET_INCOME,
    "당기순이익(손실)": NET_INCOME,
    "자본총계": TOTAL_EQUITY,
}

# Interest-bearing debt components. DART reports these separately, so "Total
# Debt" is derived by summing whichever ones a filer discloses. This mirrors
# yfinance's "Total Debt" (short-term + long-term borrowings), which is a
# narrower figure than 부채총계 (total liabilities).
DEBT_COMPONENT_NAMES: set[str] = {
    "단기차입금",
    "장기차입금",
    "유동성장기부채",
    "유동성장기차입금",
    "사채",
    "유동성사채",
    "전환사채",
    "신주인수권부사채",
}

DEBT_COMPONENT_IDS: set[str] = {
    "ifrs-full_ShorttermBorrowings",
    "ifrs-full_LongtermBorrowings",
    "ifrs-full_CurrentPortionOfLongtermBorrowings",
    "dart_ShortTermBorrowings",
    "dart_LongTermBorrowings",
}


def normalize_name(raw: str | None) -> str:
    """Strip whitespace so ``매출채권 및 기타채권`` matches ``매출채권및기타채권``.

    Args:
        raw: Raw ``account_nm`` value from DART.

    Returns:
        Whitespace-free account name, or an empty string when input is missing.
    """
    if not raw:
        return ""
    return "".join(raw.split())


def map_account(
    account_id: str | None,
    account_nm: str | None,
    statement: str | None = None,
) -> str | None:
    """Translate a DART account into this project's account name.

    Args:
        account_id: IFRS tag from DART (``account_id`` field).
        account_nm: Korean account name from DART (``account_nm`` field).
        statement: DART statement division (``sj_div``). When given, the account
            is rejected unless it belongs to a statement that carries it - this
            is what keeps equity-component rows in the statement of changes in
            equity from being read as total equity.

    Returns:
        Mapped English account name, or None when the account is not one the
        metrics layer needs or comes from the wrong statement.
    """
    mapped = None

    if account_id:
        mapped = ACCOUNT_ID_MAP.get(account_id.strip())

    if mapped is None:
        mapped = ACCOUNT_NAME_MAP.get(normalize_name(account_nm))

    if mapped is None:
        return None

    if statement is not None:
        allowed = ACCOUNT_STATEMENTS.get(mapped)
        if allowed is not None and statement.strip().upper() not in allowed:
            return None

    return mapped


def is_debt_component(
    account_id: str | None,
    account_nm: str | None,
    statement: str | None = None,
) -> bool:
    """Whether an account contributes to derived interest-bearing total debt.

    Args:
        account_id: IFRS tag from DART.
        account_nm: Korean account name from DART.
        statement: DART statement division (``sj_div``). Borrowings are balance
            sheet items; the same labels appear in the cash flow statement as
            movements, which must not be summed into a balance.

    Returns:
        True when the account is a borrowing or bond line item.
    """
    if statement is not None and statement.strip().upper() != BALANCE_SHEET:
        return False

    if account_id and account_id.strip() in DEBT_COMPONENT_IDS:
        return True
    return normalize_name(account_nm) in DEBT_COMPONENT_NAMES
