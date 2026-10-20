"""Finviz screener connector.

Uses the Finviz Elite CSV export (https://elite.finviz.com/export.ashx), which is the
supported programmatic access path. Set FINVIZ_API_TOKEN to your Elite auth token
(Finviz Elite -> Account -> API / export link contains `auth=...`).
"""
from __future__ import annotations

import io
import logging
import os

import pandas as pd
import requests

log = logging.getLogger(__name__)

EXPORT_URL = "https://elite.finviz.com/export.ashx"


class FinvizError(RuntimeError):
    pass


class FinvizScreener:
    def __init__(self, token: str | None = None, session: requests.Session | None = None):
        self.token = token or os.environ.get("FINVIZ_API_TOKEN")
        if not self.token:
            raise FinvizError("FINVIZ_API_TOKEN is not set (Finviz Elite export token required)")
        self.session = session or requests.Session()

    def screen(self, filters: str, max_symbols: int = 50, order: str = "-averagevolume") -> pd.DataFrame:
        """Run a screener and return the export as a DataFrame (one row per ticker)."""
        params = {"v": "111", "f": filters, "o": order, "auth": self.token}
        resp = self.session.get(EXPORT_URL, params=params, timeout=30,
                                headers={"User-Agent": "swing-agent/1.0"})
        if resp.status_code != 200:
            raise FinvizError(f"Finviz export failed: HTTP {resp.status_code}")
        text = resp.text.lstrip("﻿")
        if not text.startswith('"No.') and not text.startswith("No."):
            raise FinvizError("Unexpected Finviz response (bad token or filters?)")
        df = pd.read_csv(io.StringIO(text))
        log.info("Finviz screen returned %d symbols", len(df))
        return df.head(max_symbols)

    def tickers(self, filters: str, max_symbols: int = 50) -> list[str]:
        return self.screen(filters, max_symbols)["Ticker"].astype(str).tolist()
