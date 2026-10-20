"""Execution: local paper broker (default) and Alpaca REST broker.

Finviz and Bloomberg are data sources only; orders go through a broker.
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class Broker(ABC):
    @abstractmethod
    def equity(self, prices: dict[str, float]) -> float: ...
    @abstractmethod
    def cash(self) -> float: ...
    @abstractmethod
    def positions(self) -> dict[str, dict]: ...
    @abstractmethod
    def buy(self, ticker: str, qty: int, price: float, stop: float, target: float, date: str) -> None: ...
    @abstractmethod
    def sell(self, ticker: str, price: float, reason: str) -> None: ...


class PaperBroker(Broker):
    """Simulated account persisted to JSON. Fills at the supplied price."""

    def __init__(self, state_file: str, starting_cash: float = 100_000):
        self.path = Path(state_file)
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {"cash": starting_cash, "positions": {}, "trades": []}
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2))

    def cash(self) -> float:
        return self.state["cash"]

    def positions(self) -> dict[str, dict]:
        return self.state["positions"]

    def equity(self, prices: dict[str, float]) -> float:
        return self.state["cash"] + sum(p["qty"] * prices.get(t, p["entry"]) for t, p in self.positions().items())

    def buy(self, ticker, qty, price, stop, target, date):
        cost = qty * price
        if cost > self.state["cash"]:
            raise ValueError(f"insufficient cash for {ticker}")
        self.state["cash"] -= cost
        self.state["positions"][ticker] = {"qty": qty, "entry": price, "stop": stop, "target": target, "entry_date": date}
        self.state["trades"].append({"side": "buy", "ticker": ticker, "qty": qty, "price": price, "date": date})
        self._save()
        log.info("PAPER BUY %s x%d @ %.2f stop %.2f target %.2f", ticker, qty, price, stop, target)

    def sell(self, ticker, price, reason):
        pos = self.state["positions"].pop(ticker)
        self.state["cash"] += pos["qty"] * price
        pnl = (price - pos["entry"]) * pos["qty"]
        self.state["trades"].append({"side": "sell", "ticker": ticker, "qty": pos["qty"], "price": price,
                                     "reason": reason, "pnl": round(pnl, 2)})
        self._save()
        log.info("PAPER SELL %s x%d @ %.2f (%s) pnl %.2f", ticker, pos["qty"], price, reason, pnl)


class AlpacaBroker(Broker):
    """Alpaca Trading API v2. Entries are bracket orders so stop/target live at the broker,
    protecting positions even if this agent is offline."""

    def __init__(self, base_url: str, state_file: str):
        key, secret = os.environ.get("ALPACA_API_KEY_ID"), os.environ.get("ALPACA_API_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set")
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        # local metadata (entry date, stop/target) for positions the agent opened
        self.meta_path = Path(state_file).with_name("alpaca_meta.json")
        self.meta = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

    def _req(self, method, path, **kw):
        r = self.s.request(method, f"{self.base}/v2{path}", timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def _save_meta(self):
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(self.meta, indent=2))

    def cash(self) -> float:
        return float(self._req("GET", "/account")["cash"])

    def equity(self, prices) -> float:
        return float(self._req("GET", "/account")["equity"])

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self._req("GET", "/positions"):
            t = p["symbol"]
            m = self.meta.get(t, {})
            out[t] = {"qty": int(float(p["qty"])), "entry": float(p["avg_entry_price"]),
                      "stop": m.get("stop", 0.0), "target": m.get("target", float("inf")),
                      "entry_date": m.get("entry_date", "1970-01-01")}
        return out

    def buy(self, ticker, qty, price, stop, target, date):
        self._req("POST", "/orders", json={
            "symbol": ticker, "qty": str(qty), "side": "buy", "type": "market", "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": f"{target:.2f}"},
            "stop_loss": {"stop_price": f"{stop:.2f}"},
        })
        self.meta[ticker] = {"stop": stop, "target": target, "entry_date": date}
        self._save_meta()
        log.info("ALPACA BUY %s x%d (bracket stop %.2f target %.2f)", ticker, qty, stop, target)

    def sell(self, ticker, price, reason):
        # cancel the bracket legs, then flatten
        for o in self._req("GET", "/orders", params={"status": "open", "symbols": ticker}):
            self._req("DELETE", f"/orders/{o['id']}")
        self._req("DELETE", f"/positions/{ticker}")
        self.meta.pop(ticker, None)
        self._save_meta()
        log.info("ALPACA SELL %s (%s)", ticker, reason)
