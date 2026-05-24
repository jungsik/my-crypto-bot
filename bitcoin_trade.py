import datetime
import time

import pyupbit

import bot_runtime as rt
from strategy.config import load_strategy_config
from strategy.performance_guard import PerformanceGuard
from strategy.portfolio_guard import PortfolioGuard
from strategy.signals import should_buy
from trading_actions import get_market_data, try_sell_position

# =========================================================
# 업비트 멀티 레짐 자동매매 v4
# - 15분 cron: 매수 + 전체 스캔·매도
# - 1분 cron: position_watcher.py (보유만 매도)
# - PerformanceGuard: 일일 손실·연속 손절 시 매수 중단
# =========================================================


def main():
    print("\n==============================")
    print("[START]", datetime.datetime.now())
    print(f"[MODE] DRY_RUN={1 if rt.DRY_RUN else 0}")

    cfg = load_strategy_config()
    state = rt.load_state()
    guard = PortfolioGuard(cfg, state)
    perf = PerformanceGuard(cfg, state)

    tickers = [t for t in cfg.position_priority if t in cfg.target_coins]
    tickers += [t for t in cfg.target_coins if t not in tickers]

    snapshots: dict[str, dict] = {}
    prices: dict[str, float] = {}

    for ticker in tickers:
        try:
            market = get_market_data(ticker, cfg)
            if not market:
                continue
            price = pyupbit.get_current_price(ticker)
            if not price:
                continue
            snapshots[ticker] = market
            prices[ticker] = float(price)
            currency = ticker.split("-")[-1]
            print(
                f"[{currency}] mode={market['mode']} price={price:,.0f} "
                f"RSI={market['rsi']:.1f} ADX={market['adx']:.1f}"
            )
            time.sleep(0.15)
        except Exception as exc:
            print("[SCAN ERROR]", ticker, exc)

    equity = rt.estimate_equity_krw(cfg)
    perf.refresh_daily_start_equity(equity)
    pnl = perf.daily_pnl_pct(equity)
    print(f"[EQUITY] {equity:,.0f} KRW daily_pnl={pnl:+.2f}%")

    for ticker in tickers:
        if ticker in snapshots and rt.collect_holdings(cfg).get(ticker):
            try_sell_position(ticker, cfg, state, perf, source="trade")

    holdings = rt.collect_holdings(cfg)
    can_buy, pause_reason = perf.can_open_new_buys(equity)
    if not can_buy:
        print(f"[PERF GUARD] buys paused: {pause_reason}")
        rt.save_state(state)
        print(f"[END] open={guard.open_position_count(holdings)} daily_buys={guard.daily_buy_count}")
        return

    open_count = guard.open_position_count(holdings)
    buys_this_run = 0
    candidates = []

    for ticker in tickers:
        if ticker not in snapshots or holdings.get(ticker):
            continue
        if should_buy(prices[ticker], snapshots[ticker], cfg):
            candidates.append({"ticker": ticker, "market": snapshots[ticker]})

    for item in guard.sort_buy_candidates(candidates):
        ticker = item["ticker"]
        currency = ticker.split("-")[-1]
        market = item["market"]
        current_price = prices[ticker]

        krw = rt.get_balance("KRW")
        buy_amount = min(cfg.buy_amount_krw, krw)
        ok, skip_reason = guard.can_buy(
            open_positions=open_count,
            buys_this_run=buys_this_run,
            available_krw=krw,
            buy_amount=buy_amount,
        )
        if not ok:
            print(f"[SKIP BUY] {currency} reason={skip_reason}")
            continue

        if rt.buy_coin(ticker, buy_amount, cfg):
            rt.send_telegram(
                f"[BUY] {currency}\nmode: {market['mode']}\n"
                f"price: {current_price:,.0f}\nRSI: {market['rsi']:.1f} ADX: {market['adx']:.1f}"
            )
            guard.record_buy()
            open_count += 1
            buys_this_run += 1
            holdings[ticker] = True

    rt.save_state(state)
    print(
        f"[END] open={guard.open_position_count(rt.collect_holdings(cfg))} "
        f"daily_buys={guard.daily_buy_count} consec_losses={state.get('consecutive_losses', 0)}"
    )


if __name__ == "__main__":
    main()
