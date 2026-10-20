# Swing Agent

Autonomous daily swing-trading agent:

```
Finviz Elite screener ──► universe of tickers
Bloomberg (blpapi)    ──► daily OHLCV bars
Strategy              ──► exits for held names, ranked entry signals
Risk manager          ──► position sizing, exposure caps, kill switch
Broker                ──► paper (default) or Alpaca bracket orders
```

## Strategy (trend pullback)
- **Trend:** SMA50 > SMA200, close > SMA200, SMA50 rising
- **Entry:** RSI(14) dipped to ≤ 45 and is turning up, and close > yesterday's high
- **Exits:** stop at 2×ATR, target at 4×ATR, close below SMA20, or 15-day time stop
- **Sizing:** risk 1% of equity per trade, ≤ 15% per name, ≤ 6 positions, ≤ 80% gross
- **Safety:** halts new entries after a 3% daily drawdown. Create `state/HALT` to stop all trading.

All parameters are in `config.yaml`.

## Setup
```bash
pip install -r requirements.txt
pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi
export FINVIZ_API_TOKEN=...            # Finviz Elite export token
# Bloomberg: run on a machine with a logged-in Terminal (localhost:8194) or set host/port for B-PIPE
```

## Run
```bash
python -m swing_agent --once --demo    # offline: synthetic data + paper account
python -m swing_agent --once           # one real cycle (Finviz + Bloomberg, paper broker)
python -m swing_agent --loop           # autonomous: runs every weekday at 15:45 ET
python -m pytest -q
```

### Placing real orders
Set `broker.kind: alpaca` and export `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY`.
The default URL is Alpaca **paper**. For live trading, change `alpaca_base_url` to
`https://api.alpaca.markets` **and** export `SWING_AGENT_LIVE=YES`, or the agent refuses to start.
Entries go in as bracket orders, so the stop and target stay at the broker while the agent is offline.

## Caveats
- Paper the strategy before you use real money. The rules are a reasonable starting point. They haven't been backtested.
- Bloomberg Terminal data licenses usually limit automated or non-display use. Check yours (B-PIPE may be required).
- The paper broker fills at the last close and doesn't model slippage or commissions.
