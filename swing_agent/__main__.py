"""CLI: python -m swing_agent [--once | --loop] [--demo] [--config config.yaml]"""
from __future__ import annotations

import argparse
import json
import logging
import os

import yaml

from .agent import SwingAgent
from .broker import AlpacaBroker, PaperBroker


def build(cfg: dict, demo: bool):
    if demo:
        from .demo import DemoData, DemoScreener
        screener, data = DemoScreener(), DemoData()
    else:
        from .bloomberg import BloombergData
        from .finviz import FinvizScreener
        b = cfg["bloomberg"]
        screener = FinvizScreener()
        data = BloombergData(b["host"], b["port"], b["ticker_suffix"])

    bc = cfg["broker"]
    if bc["kind"] == "alpaca" and not demo:
        if "paper-api" not in bc["alpaca_base_url"] and os.environ.get("SWING_AGENT_LIVE") != "YES":
            raise SystemExit("Refusing live trading: set SWING_AGENT_LIVE=YES to confirm real-money orders.")
        broker = AlpacaBroker(bc["alpaca_base_url"], bc["state_file"])
    else:
        broker = PaperBroker(bc["state_file"], bc["paper_starting_cash"])
    return SwingAgent(cfg, screener, data, broker)


def main() -> None:
    ap = argparse.ArgumentParser(prog="swing_agent")
    ap.add_argument("--config", default="config.yaml")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run one cycle now and exit")
    mode.add_argument("--loop", action="store_true", help="run autonomously on the daily schedule")
    ap.add_argument("--demo", action="store_true", help="synthetic data + paper broker (no credentials needed)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("swing_agent.log")])
    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if args.demo:
        cfg["broker"]["state_file"] = "state/demo_account.json"

    agent = build(cfg, args.demo)
    if args.loop:
        agent.run_forever()
    else:
        print(json.dumps(agent.run_once(), indent=2))


if __name__ == "__main__":
    main()
