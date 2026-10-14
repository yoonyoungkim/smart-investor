"""High-level helper to persist collected DataFrames to the database.

Bridges the collection scripts and the :class:`DataPersistence` layer so each
script only needs to build persistence-ready DataFrames and hand them off here.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
from smart_investor.db.persistence import DataPersistence

logger = logging.getLogger(__name__)

# Maps a key in the ``collected`` dict to the DataPersistence method that saves it.
_SAVE_METHODS = {
    "tickers": "save_tickers",
    "etfs": "save_etfs",
    "prices": "save_prices",
    "financials": "save_financials",
    "dividends": "save_dividends",
    "values": "save_values",
}

# Human-readable labels for logging.
_LABELS = {
    "tickers": "티커",
    "etfs": "ETF",
    "prices": "가격",
    "financials": "재무",
    "dividends": "배당",
    "values": "지표",
}


def persist_dataframes(
    persistence: DataPersistence,
    collected: dict[str, Optional[pd.DataFrame]],
) -> dict[str, int]:
    """Save collected DataFrames using an existing persistence layer.

    Args:
        persistence: Persistence layer bound to an open session.
        collected: Mapping of data type ("tickers", "prices", "financials",
            "dividends") to its DataFrame. ``None`` or empty frames are skipped.

    Returns:
        Mapping of data type to the number of records inserted/updated.
    """
    counts: dict[str, int] = {}

    for key, method_name in _SAVE_METHODS.items():
        df = collected.get(key)
        if df is None or df.empty:
            continue

        save = getattr(persistence, method_name)
        try:
            saved = save(df)
            counts[key] = saved
            logger.info(f"💾 {_LABELS[key]} 저장 완료: {saved}건")
        except Exception as e:
            logger.error(f"❌ {_LABELS[key]} 저장 실패: {e}", exc_info=True)

    return counts


def save_collected_data(
    collected: dict[str, Optional[pd.DataFrame]],
    config: Optional[DatabaseConfig] = None,
) -> dict[str, int]:
    """Open a database connection and persist all collected DataFrames.

    Args:
        collected: Mapping of data type to its DataFrame (see
            :func:`persist_dataframes`).
        config: Optional database configuration. Loaded from environment
            variables when omitted.

    Returns:
        Mapping of data type to the number of records inserted/updated.
    """
    if not any(df is not None and not df.empty for df in collected.values()):
        logger.warning("저장할 데이터가 없습니다.")
        return {}

    if config is None:
        config = DatabaseConfig.from_env()

    with DatabaseConnection(config) as db:
        session = db.get_session()
        try:
            persistence = DataPersistence(session)
            return persist_dataframes(persistence, collected)
        finally:
            session.close()
