"""매도 실행·손익 기록 공통 로직."""

import pyupbit

import bot_runtime as rt
from strategy.config import StrategyConfig
from strategy.performance_guard import PerformanceGuard
from strategy.regime import build_market_snapshot
from strategy.signals import get_sell_signal


def get_market_data(ticker: str, cfg: StrategyConfig):
    try:
        df = pyupbit.get_ohlcv(ticker, interval=cfg.interval, count=100)
        return build_market_snapshot(df, cfg)
    except Exception as exc:
        print("[MARKET ERROR]", ticker, exc)
        return None


def try_sell_position(
    ticker: str,
    cfg: StrategyConfig,
    state: dict,
    perf: PerformanceGuard,
    *,
    source: str = "trade",
) -> bool:
    """보유 종목 매도 시도. 매도 실행 시 True."""
    currency = ticker.split("-")[-1]
    coin_balance = rt.get_balance(currency)
    if coin_balance <= 0.00001:
        return False

    market = get_market_data(ticker, cfg)
    if not market:
        return False

    price = pyupbit.get_current_price(ticker)
    if not price:
        return False
    current_price = float(price)

    avg_buy = rt.get_avg_buy_price(currency)
    do_sell, reason = get_sell_signal(
        current_price, avg_buy, market, state, ticker, cfg
    )
    if not do_sell:
        return False

    if rt.sell_coin(ticker, coin_balance):
        profit_pct = 0.0
        if avg_buy > 0:
            profit_pct = (current_price - avg_buy) / avg_buy * 100
        perf.record_sell(profit_pct, dry_run=rt.DRY_RUN)
        tag = "WATCH" if source == "watch" else "SELL"
        rt.send_telegram(
            f"[{tag}] {currency}\nreason: {reason}\nprice: {current_price:,.0f}\n"
            f"pnl: {profit_pct:+.2f}%"
        )
        state["highest_price"].pop(ticker, None)
        print(f"[{tag}] {currency} {reason} pnl={profit_pct:+.2f}%")
        return True
    return False
