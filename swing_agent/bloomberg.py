"""Bloomberg market-data connector (blpapi).

Requires the `blpapi` package and a running, logged-in Bloomberg Terminal (Desktop API,
localhost:8194) or a B-PIPE / Server API endpoint. Bloomberg licensing terms apply to
how this data may be used for automated trading.
"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

log = logging.getLogger(__name__)

HIST_FIELDS = ["PX_OPEN", "PX_HIGH", "PX_LOW", "PX_LAST", "PX_VOLUME"]
COLUMN_MAP = {"PX_OPEN": "open", "PX_HIGH": "high", "PX_LOW": "low",
              "PX_LAST": "close", "PX_VOLUME": "volume"}


class BloombergError(RuntimeError):
    pass


class BloombergData:
    def __init__(self, host: str = "localhost", port: int = 8194, ticker_suffix: str = " US Equity"):
        try:
            import blpapi  # noqa: F401
        except ImportError as e:
            raise BloombergError("blpapi is not installed; see requirements.txt") from e
        self._blpapi = blpapi
        self.suffix = ticker_suffix
        opts = blpapi.SessionOptions()
        opts.setServerHost(host)
        opts.setServerPort(port)
        self.session = blpapi.Session(opts)
        if not self.session.start():
            raise BloombergError(f"Could not start Bloomberg session at {host}:{port}")
        if not self.session.openService("//blp/refdata"):
            raise BloombergError("Could not open //blp/refdata")
        self.refdata = self.session.getService("//blp/refdata")

    def close(self) -> None:
        self.session.stop()

    def _sec(self, ticker: str) -> str:
        return ticker if ticker.endswith(("Equity", "Index", "Comdty", "Curncy")) else ticker + self.suffix

    def _collect(self, request) -> list:
        blpapi = self._blpapi
        self.session.sendRequest(request)
        msgs = []
        while True:
            ev = self.session.nextEvent(10_000)
            for msg in ev:
                if msg.hasElement("responseError"):
                    raise BloombergError(str(msg.getElement("responseError")))
                msgs.append(msg)
            if ev.eventType() == blpapi.Event.RESPONSE:
                return msgs
            if ev.eventType() == blpapi.Event.TIMEOUT:
                raise BloombergError("Bloomberg request timed out")

    def daily_bars(self, tickers: list[str], lookback_days: int = 300) -> dict[str, pd.DataFrame]:
        """Return {ticker: DataFrame[open,high,low,close,volume]} indexed by date."""
        req = self.refdata.createRequest("HistoricalDataRequest")
        sec_to_ticker = {}
        for t in tickers:
            sec = self._sec(t)
            sec_to_ticker[sec] = t
            req.getElement("securities").appendValue(sec)
        for f in HIST_FIELDS:
            req.getElement("fields").appendValue(f)
        end = dt.date.today()
        start = end - dt.timedelta(days=int(lookback_days * 1.5))
        req.set("startDate", start.strftime("%Y%m%d"))
        req.set("endDate", end.strftime("%Y%m%d"))
        req.set("periodicitySelection", "DAILY")
        req.set("adjustmentSplit", True)
        req.set("adjustmentNormal", True)

        out: dict[str, pd.DataFrame] = {}
        for msg in self._collect(req):
            if not msg.hasElement("securityData"):
                continue
            sd = msg.getElement("securityData")
            sec = sd.getElementAsString("security")
            if sd.hasElement("securityError"):
                log.warning("Bloomberg error for %s: %s", sec, sd.getElement("securityError"))
                continue
            fd = sd.getElement("fieldData")
            rows = []
            for i in range(fd.numValues()):
                pt = fd.getValueAsElement(i)
                row = {"date": pd.Timestamp(pt.getElementAsDatetime("date"))}
                for f in HIST_FIELDS:
                    if pt.hasElement(f):
                        row[COLUMN_MAP[f]] = pt.getElementAsFloat(f)
                rows.append(row)
            if rows:
                df = pd.DataFrame(rows).set_index("date").sort_index().dropna()
                out[sec_to_ticker.get(sec, sec)] = df.tail(lookback_days)
        return out

    def last_prices(self, tickers: list[str]) -> dict[str, float]:
        req = self.refdata.createRequest("ReferenceDataRequest")
        sec_to_ticker = {}
        for t in tickers:
            sec = self._sec(t)
            sec_to_ticker[sec] = t
            req.getElement("securities").appendValue(sec)
        req.getElement("fields").appendValue("PX_LAST")
        out = {}
        for msg in self._collect(req):
            if not msg.hasElement("securityData"):
                continue
            arr = msg.getElement("securityData")
            for i in range(arr.numValues()):
                sd = arr.getValueAsElement(i)
                fd = sd.getElement("fieldData")
                if fd.hasElement("PX_LAST"):
                    sec = sd.getElementAsString("security")
                    out[sec_to_ticker.get(sec, sec)] = fd.getElementAsFloat("PX_LAST")
        return out
