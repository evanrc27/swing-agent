"""Synthetic stand-ins for Finviz/Bloomberg so the full loop can be exercised offline."""
from __future__ import annotations

import numpy as np
import pandas as pd

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]


def synthetic_bars(seed: int, n: int = 300, pullback: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.003, 0.01, n)
    if pullback:  # uptrend, a 5-day dip, then a strong up day
        rets[-6:-1] = -0.012
        rets[-1] = 0.025
    close = 50 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.002, 0.012, n))
    low = close * (1 - rng.uniform(0.002, 0.012, n))
    open_ = np.r_[close[0], close[:-1]]
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame({"open": open_, "high": np.maximum(high, open_), "low": np.minimum(low, open_),
                         "close": close, "volume": rng.integers(1_000_000, 3_000_000, n).astype(float)}, index=idx)


class DemoScreener:
    def tickers(self, filters: str, max_symbols: int = 50) -> list[str]:
        return TICKERS[:max_symbols]


class DemoData:
    def daily_bars(self, tickers, lookback_days=300):
        return {t: synthetic_bars(i, lookback_days, pullback=(i % 2 == 0))
                for i, t in enumerate(TICKERS) if t in tickers}
