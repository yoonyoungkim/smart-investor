"""DART OpenAPI client for Korean corporate disclosure data.

DART (전자공시시스템, https://opendart.fss.or.kr) is the Financial Supervisory
Service's official disclosure system. It is the only free source that provides
complete Korean financial statements, which pykrx and FinanceDataReader do not.

Requires a free API key from https://opendart.fss.or.kr/ set as ``DART_API_KEY``.
"""

from __future__ import annotations

import io
import logging
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests

from smart_investor.db.config import load_env

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"

# Report codes used by DART. 11011 (annual business report) is the only one that
# carries full-year figures, which is what the yearly ("y") frequency needs.
REPORT_ANNUAL = "11011"
REPORT_HALF = "11012"
REPORT_Q1 = "11013"
REPORT_Q3 = "11014"

# Consolidated statements first, separate ones as fallback for companies that
# have no subsidiaries and therefore file no consolidated report.
FS_CONSOLIDATED = "CFS"
FS_SEPARATE = "OFS"

# Where the corp_code ↔ stock_code mapping is cached after the first download.
# The mapping file is ~20MB zipped and changes rarely, so re-downloading it on
# every run would be wasteful.
CACHE_DIR = Path.home() / ".cache" / "smart-investor"
CORP_CODE_CACHE = CACHE_DIR / "dart_corp_codes.tsv"
CORP_CODE_MAX_AGE_DAYS = 30


class DartError(RuntimeError):
    """Raised when the DART API returns a non-recoverable error."""


class DartApiKeyError(DartError):
    """Raised when no DART API key is configured."""


@dataclass
class DartStatus:
    """Decoded ``status``/``message`` pair returned by every DART endpoint."""

    code: str
    message: str

    @property
    def ok(self) -> bool:
        """Whether the response carries usable data."""
        return self.code == "000"

    @property
    def no_data(self) -> bool:
        """Whether the request was valid but matched no disclosure."""
        # 013 = 조회된 데이터가 없습니다.
        return self.code == "013"

    @property
    def rate_limited(self) -> bool:
        """Whether the daily request quota has been exhausted."""
        # 020 = 요청 제한을 초과하였습니다. (20,000 requests/day)
        return self.code == "020"


class DartClient:
    """Thin client over the DART OpenAPI REST endpoints.

    Args:
        api_key: DART certification key. Falls back to ``DART_API_KEY``.
        delay: Seconds to sleep between requests. DART allows 20,000 requests
            per day; a small delay keeps bulk collection from tripping limits.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        delay: float = 0.0,
        timeout: float = 20.0,
    ) -> None:
        # Collectors are often built before any database call, so .env has to be
        # loaded here rather than relying on DatabaseConfig having run first.
        if api_key is None:
            load_env()
        self.api_key = api_key or os.getenv("DART_API_KEY")
        self.delay = delay
        self.timeout = timeout
        self._corp_codes: dict[str, str] | None = None
        self._session = requests.Session()

    @property
    def configured(self) -> bool:
        """Whether an API key is available."""
        return bool(self.api_key)

    def require_key(self) -> str:
        """Return the API key, raising a helpful error when it is missing."""
        if not self.api_key:
            raise DartApiKeyError(
                "DART_API_KEY is not set. Register for a free key at "
                "https://opendart.fss.or.kr/ and add DART_API_KEY=<key> to .env"
            )
        return self.api_key

    def get_json(self, endpoint: str, **params: Any) -> tuple[DartStatus, list[dict[str, Any]]]:
        """Call a JSON endpoint and split the status from the payload.

        Args:
            endpoint: Endpoint name, e.g. ``fnlttSinglAcntAll``.
            **params: Query parameters, excluding the certification key.

        Returns:
            Tuple of (status, list rows). The list is empty unless status is OK.
        """
        params = {"crtfc_key": self.require_key(), **params}
        url = f"{BASE_URL}/{endpoint}.json"

        if self.delay:
            time.sleep(self.delay)

        response = self._session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()

        status = DartStatus(
            code=str(payload.get("status", "")),
            message=str(payload.get("message", "")),
        )

        if status.rate_limited:
            raise DartError(f"DART request limit exceeded: {status.message}")

        rows = payload.get("list", []) if status.ok else []
        return status, rows

    # ------------------------------------------------------------------
    # corp_code mapping
    # ------------------------------------------------------------------

    def corp_code_map(self, refresh: bool = False) -> dict[str, str]:
        """Return a ``{stock_code: corp_code}`` mapping.

        DART identifies companies by an 8-digit ``corp_code`` rather than the
        6-digit KRX ticker, so every lookup needs this translation table.

        Args:
            refresh: Re-download even when a fresh cache exists.

        Returns:
            Mapping of 6-digit stock code to 8-digit DART corp code.
        """
        if self._corp_codes is not None and not refresh:
            return self._corp_codes

        if not refresh and self._cache_is_fresh():
            self._corp_codes = self._read_cache()
            logger.info(f"Loaded {len(self._corp_codes)} DART corp codes from cache")
            return self._corp_codes

        self._corp_codes = self._download_corp_codes()
        self._write_cache(self._corp_codes)
        logger.info(f"Downloaded {len(self._corp_codes)} DART corp codes")
        return self._corp_codes

    def corp_code(self, stock_code: str) -> str | None:
        """Translate a 6-digit KRX ticker into a DART corp code.

        Args:
            stock_code: 6-digit Korean stock code.

        Returns:
            8-digit corp code, or None when the ticker is not listed in DART.
        """
        return self.corp_code_map().get(stock_code.zfill(6))

    def _cache_is_fresh(self) -> bool:
        """Whether the on-disk corp code cache exists and is recent enough."""
        if not CORP_CODE_CACHE.exists():
            return False
        age_days = (time.time() - CORP_CODE_CACHE.stat().st_mtime) / 86400
        return age_days < CORP_CODE_MAX_AGE_DAYS

    def _read_cache(self) -> dict[str, str]:
        """Load the cached mapping from disk."""
        mapping: dict[str, str] = {}
        with CORP_CODE_CACHE.open(encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 2:
                    mapping[parts[0]] = parts[1]
        return mapping

    def _write_cache(self, mapping: dict[str, str]) -> None:
        """Persist the mapping so later runs skip the 20MB download."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with CORP_CODE_CACHE.open("w", encoding="utf-8") as fh:
            for stock_code, corp in sorted(mapping.items()):
                fh.write(f"{stock_code}\t{corp}\n")

    def _download_corp_codes(self) -> dict[str, str]:
        """Fetch and parse the corpCode.xml archive from DART."""
        url = f"{BASE_URL}/corpCode.xml"
        response = self._session.get(
            url,
            params={"crtfc_key": self.require_key()},
            timeout=max(self.timeout, 60.0),
        )
        response.raise_for_status()

        # A JSON body here means an error status instead of the expected ZIP.
        if response.headers.get("Content-Type", "").startswith("application/json"):
            payload = response.json()
            raise DartError(
                f"corpCode download failed: {payload.get('status')} {payload.get('message')}"
            )

        mapping: dict[str, str] = {}
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            name = archive.namelist()[0]
            with archive.open(name) as fh:
                tree = ElementTree.parse(fh)

        for item in tree.iter("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp = (item.findtext("corp_code") or "").strip()
            # Non-listed companies carry a blank stock_code; skip them.
            if stock_code and corp:
                mapping[stock_code] = corp

        return mapping
