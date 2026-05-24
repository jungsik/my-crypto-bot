#!/usr/bin/env python3
"""하위 호환 래퍼 — 신규 엔진은 run_backtest.py 또는 backtest.optimizer 사용."""

import argparse

from backtest.optimizer import optimize, print_results, write_strategy_config
from strategy.config import load_strategy_config


def parse_args():
    parser = argparse.ArgumentParser(description="Optimize RSI/volume (multi-regime engine)")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--count", type=int, default=8640)
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--write-config", default="strategy_config.json")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cfg = load_strategy_config()
    tickers = args.tickers or cfg.target_coins
    top_results = optimize(tickers, args.count, args.cash, args.top, base_cfg=cfg)
    print_results(top_results)
    if args.write_config:
        write_strategy_config(top_results, args.write_config, tickers, args.count, base_cfg=cfg)
