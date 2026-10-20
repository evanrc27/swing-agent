"""The autonomous loop: screen (Finviz) -> data (Bloomberg) -> exits -> entries -> broker."""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .strategy import entry_signal, exit_reason

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")


class SwingAgent:
    def __init__(self, cfg: dict, screener, data, broker):
        self.cfg, self.screener, self.data, self.broker = cfg, screener, data, broker
        self.halt_file = Path(cfg["broker"]["state_file"]).with_name("HALT")
        self.day_state_file = Path(cfg["broker"]["state_file"]).with_name("day_state.json")

    # ---- risk helpers ----
    def _start_of_day_equity(self, equity: float, today: str) -> float:
        st = json.loads(self.day_state_file.read_text()) if self.day_state_file.exists() else {}
        if st.get("date") != today:
            st = {"date": today, "equity": equity}
            self.day_state_file.parent.mkdir(parents=True, exist_ok=True)
            self.day_state_file.write_text(json.dumps(st))
        return st["equity"]

    def _size(self, sig, equity: float, cash: float, gross: float) -> int:
        r = self.cfg["risk"]
        per_share_risk = sig.entry - sig.stop
        if per_share_risk <= 0:
            return 0
        qty = int(equity * r["risk_per_trade_pct"] / 100 / per_share_risk)
        qty = min(qty, int(equity * r["max_position_pct"] / 100 / sig.entry))
        room = equity * r["max_gross_exposure_pct"] / 100 - gross
        qty = min(qty, int(max(room, 0) / sig.entry), int(cash / sig.entry))
        return max(qty, 0)

    # ---- one full decision cycle ----
    def run_once(self, now: dt.datetime | None = None) -> dict:
        now = now or dt.datetime.now(NY)
        today = now.strftime("%Y-%m-%d")
        report = {"date": today, "exits": [], "entries": [], "halted": False}

        if self.halt_file.exists():
            log.warning("HALT file present (%s); skipping cycle", self.halt_file)
            report["halted"] = True
            return report

        positions = self.broker.positions()
        universe = self.screener.tickers(self.cfg["finviz"]["filters"], self.cfg["finviz"]["max_symbols"])
        symbols = sorted(set(universe) | set(positions))
        bars = self.data.daily_bars(symbols, self.cfg["bloomberg"]["lookback_days"])
        prices = {t: float(df["close"].iloc[-1]) for t, df in bars.items() if len(df)}

        # 1) manage exits
        for t, pos in list(positions.items()):
            if t not in bars:
                log.warning("No data for held position %s; leaving it alone", t)
                continue
            reason = exit_reason(bars[t], pos, self.cfg["strategy"], pd.Timestamp(today))
            if reason:
                px = prices[t]
                if reason == "stop":
                    px = min(px, pos["stop"])
                elif reason == "target":
                    px = max(px, pos["target"])
                self.broker.sell(t, px, reason)
                report["exits"].append({"ticker": t, "reason": reason, "price": round(px, 2)})

        # 2) kill switch
        equity = self.broker.equity(prices)
        sod = self._start_of_day_equity(equity, today)
        if sod and (sod - equity) / sod * 100 >= self.cfg["risk"]["daily_loss_limit_pct"]:
            log.error("Daily loss limit hit (%.2f -> %.2f); no new entries today", sod, equity)
            report["halted"] = True
            return report

        # 3) new entries
        positions = self.broker.positions()
        slots = self.cfg["risk"]["max_positions"] - len(positions)
        if slots > 0:
            sigs = [s for t in universe if t not in positions and t in bars
                    and (s := entry_signal(t, bars[t], self.cfg["strategy"]))]
            sigs.sort(key=lambda s: s.score, reverse=True)
            gross = sum(p["qty"] * prices.get(t, p["entry"]) for t, p in positions.items())
            for sig in sigs[:slots]:
                qty = self._size(sig, equity, self.broker.cash(), gross)
                if qty < 1:
                    continue
                self.broker.buy(sig.ticker, qty, sig.entry, round(sig.stop, 2), round(sig.target, 2), today)
                gross += qty * sig.entry
                report["entries"].append({"ticker": sig.ticker, "qty": qty, "entry": round(sig.entry, 2),
                                          "stop": round(sig.stop, 2), "target": round(sig.target, 2)})

        report["equity"] = round(self.broker.equity(prices), 2)
        log.info("Cycle report: %s", report)
        return report

    # ---- scheduler ----
    def run_forever(self) -> None:
        sch = self.cfg["schedule"]
        hh, mm = map(int, sch["run_time"].split(":"))
        last_run = None
        log.info("Agent started; will run daily at %s America/New_York", sch["run_time"])
        while True:
            now = dt.datetime.now(NY)
            due = now.hour > hh or (now.hour == hh and now.minute >= mm)
            if due and last_run != now.date() and not (sch["weekdays_only"] and now.weekday() >= 5):
                try:
                    self.run_once(now)
                except Exception:
                    log.exception("Cycle failed; will retry next day")
                last_run = now.date()
            time.sleep(30)
