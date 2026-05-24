#!/usr/bin/env python3
"""보유 종목만 주기적으로 매도 감시 (cron 1분 권장)."""

import datetime
import time

import bot_runtime as rt
from strategy.config import load_strategy_config
from strategy.performance_guard import PerformanceGuard
from trading_actions import try_sell_position


def main():
    print("\n==============================")
    print("[WATCH START]", datetime.datetime.now())
    if rt.DRY_RUN:
        print("[MODE] DRY_RUN")

    cfg = load_strategy_config()
    state = rt.load_state()
    perf = PerformanceGuard(cfg, state)

    held = rt.list_held_tickers(cfg)
    if not held:
        print("[WATCH] no positions")
        rt.save_state(state)
        return

    sold = 0
    for ticker in held:
        if try_sell_position(ticker, cfg, state, perf, source="watch"):
            sold += 1
        time.sleep(0.15)

    rt.save_state(state)
    print(f"[WATCH END] checked={len(held)} sold={sold}")


if __name__ == "__main__":
    main()
