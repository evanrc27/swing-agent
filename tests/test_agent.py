import pandas as pd
import pytest
import yaml

from swing_agent.agent import SwingAgent
from swing_agent.broker import PaperBroker
from swing_agent.demo import DemoData, DemoScreener, synthetic_bars
from swing_agent.strategy import entry_signal, exit_reason


@pytest.fixture
def cfg(tmp_path):
    with open("config.yaml") as f:
        c = yaml.safe_load(f)
    c["broker"]["state_file"] = str(tmp_path / "acct.json")
    return c


def make_agent(cfg):
    broker = PaperBroker(cfg["broker"]["state_file"], 100_000)
    return SwingAgent(cfg, DemoScreener(), DemoData(), broker), broker


def test_pullback_generates_signal(cfg):
    sig = entry_signal("X", synthetic_bars(0, pullback=True), cfg["strategy"])
    assert sig and sig.stop < sig.entry < sig.target


def test_cycle_respects_risk_limits(cfg):
    agent, broker = make_agent(cfg)
    report = agent.run_once()
    assert report["entries"], "demo data should produce entries"
    r = cfg["risk"]
    assert len(broker.positions()) <= r["max_positions"]
    for e in report["entries"]:
        assert e["qty"] * (e["entry"] - e["stop"]) <= 100_000 * r["risk_per_trade_pct"] / 100 + 1
        assert e["qty"] * e["entry"] <= 100_000 * r["max_position_pct"] / 100 + 1
    assert broker.cash() >= 0


def test_stop_exit(cfg):
    df = synthetic_bars(1)
    pos = {"qty": 10, "entry": 100, "stop": df["low"].iloc[-1] + 1, "target": 1e9,
           "entry_date": str(df.index[-3].date())}
    assert exit_reason(df, pos, cfg["strategy"], df.index[-1]) == "stop"


def test_halt_file_stops_trading(cfg, tmp_path):
    agent, broker = make_agent(cfg)
    agent.halt_file.write_text("")
    assert agent.run_once()["halted"] and not broker.positions()


def test_daily_loss_kill_switch(cfg):
    agent, broker = make_agent(cfg)
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    agent._start_of_day_equity(200_000, today)  # pretend we started the day much higher
    report = agent.run_once()
    assert report["halted"] and not report["entries"]
