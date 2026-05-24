#!/usr/bin/env python3
"""백테스트·최적화 CLI (Oracle Cloud / 로컬 공용)."""

import argparse

import pyupbit

from backtest.engine import run_portfolio_backtest
from backtest.optimizer import load_ohlcv, optimize, print_results, write_strategy_config
from backtest.report import print_backtest_summary
from strategy.config import load_strategy_config


def parse_args():
    parser = argparse.ArgumentParser(description="Multi-regime portfolio backtest")
    parser.add_argument("--optimize", action="store_true", help="RSI/거래량 그리드 최적화")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--count", type=int, default=8640, help="15m candles (~90 days @ 8640)")
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--write-config", default="", help="최적화 후 저장 경로 (예: strategy_config.json)")
    parser.add_argument("--no-limits", action="store_true", help="포지션 한도 비활성화")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = load_strategy_config()
    tickers = args.tickers or cfg.target_coins

    if args.optimize:
        results = optimize(tickers, args.count, args.cash, args.top, base_cfg=cfg)
        print_results(results)
        if args.write_config:
            write_strategy_config(results, args.write_config, tickers, args.count, base_cfg=cfg)
        return

    data = {t: load_ohlcv(t, args.count, cfg.interval) for t in tickers}
    result = run_portfolio_backtest(data, cfg, args.cash, use_limits=not args.no_limits)
    print_backtest_summary(result, title=f"Portfolio backtest ({cfg.fill_model})")


if __name__ == "__main__":
    main()
