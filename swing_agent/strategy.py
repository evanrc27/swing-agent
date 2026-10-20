"""Swing strategy: buy RSI pullbacks inside an established uptrend, ATR-based exits."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["rsi"] = rsi(df["close"], cfg["rsi_period"])
    df["atr"] = atr(df, cfg["atr_period"])
    df["vol20"] = df["volume"].rolling(20).mean()
    return df


@dataclass
class Signal:
    ticker: str
    entry: float
    stop: float
    target: float
    score: float


def entry_signal(ticker: str, df: pd.DataFrame, cfg: dict) -> Signal | None:
    if len(df) < 205:
        return None
    d = add_indicators(df, cfg)
    t, y = d.iloc[-1], d.iloc[-2]
    uptrend = t.sma50 > t.sma200 and t.close > t.sma200 and d["sma50"].iloc[-1] > d["sma50"].iloc[-10]
    pullback = min(y.rsi, t.rsi) <= cfg["rsi_entry_max"]
    turning = (t.rsi > y.rsi and t.close > y.high) if cfg.get("rsi_turn_up", True) else True
    if not (uptrend and pullback and turning) or t.atr <= 0:
        return None
    stop = t.close - cfg["stop_atr_mult"] * t.atr
    target = t.close + cfg["target_atr_mult"] * t.atr
    # rank: stronger trend + deeper pullback + volume confirmation
    vol_ratio = min(t.volume / t.vol20, 3) if t.vol20 else 0
    score = (t.close / t.sma200 - 1) * 100 + (cfg["rsi_entry_max"] - min(y.rsi, t.rsi)) + 5 * vol_ratio
    return Signal(ticker, float(t.close), float(stop), float(target), float(score))


def exit_reason(df: pd.DataFrame, position: dict, cfg: dict, today: pd.Timestamp) -> str | None:
    """Return a reason string if the open position should be closed, else None."""
    d = add_indicators(df, cfg)
    t = d.iloc[-1]
    if t.low <= position["stop"]:
        return "stop"
    if t.high >= position["target"]:
        return "target"
    held = np.busday_count(pd.Timestamp(position["entry_date"]).date(), today.date())
    if held >= cfg["max_hold_days"]:
        return "time"
    sma = d["close"].rolling(cfg["exit_below_sma"]).mean().iloc[-1]
    if held >= 2 and t.close < sma:
        return f"close<sma{cfg['exit_below_sma']}"
    return None
