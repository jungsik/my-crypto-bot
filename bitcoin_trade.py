import datetime
import json
import os
import time
from pathlib import Path

import pyupbit
import requests

from strategy.config import StrategyConfig, load_strategy_config
from strategy.portfolio_guard import PortfolioGuard
from strategy.regime import build_market_snapshot
from strategy.signals import get_sell_signal, should_buy

# =========================================================
# 업비트 멀티 레짐 자동매매 봇 v3 (strategy 모듈 · 포지션 한도)
# Oracle Cloud cron: git pull → env.sh → python bitcoin_trade.py
# =========================================================

ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0").strip() in ("1", "true", "True", "yes")

STATE_FILE = Path("bot_state.json")

if not ACCESS_KEY or not SECRET_KEY:
    raise RuntimeError("UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 환경변수 확인 필요")

upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)


def send_telegram(message: str) -> None:
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TELEGRAM DISABLED]\n", message)
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as exc:
        print("[TELEGRAM ERROR]", exc)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"highest_price": {}, "daily_buy_count": 0, "daily_buy_date": ""}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"highest_price": {}, "daily_buy_count": 0, "daily_buy_date": ""}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_market_data(ticker: str, cfg: StrategyConfig):
    try:
        df = pyupbit.get_ohlcv(ticker, interval=cfg.interval, count=100)
        return build_market_snapshot(df, cfg)
    except Exception as exc:
        print("[MARKET ERROR]", ticker, exc)
        return None


def get_balance(currency: str) -> float:
    try:
        for item in upbit.get_balances():
            if item["currency"] == currency:
                return float(item["balance"] or 0)
        return 0.0
    except Exception:
        return 0.0


def get_avg_buy_price(currency: str) -> float:
    try:
        for item in upbit.get_balances():
            if item["currency"] == currency:
                return float(item["avg_buy_price"] or 0)
        return 0.0
    except Exception:
        return 0.0


def buy_coin(ticker: str, amount: float, cfg: StrategyConfig) -> bool:
    if DRY_RUN:
        print(f"[DRY_RUN BUY] {ticker} {amount:,.0f} KRW")
        return True
    try:
        result = upbit.buy_market_order(ticker, amount * (1 - cfg.fee_rate))
        return bool(result and result.get("uuid"))
    except Exception as exc:
        print("[BUY ERROR]", exc)
        return False


def sell_coin(ticker: str, volume: float) -> bool:
    if DRY_RUN:
        print(f"[DRY_RUN SELL] {ticker} vol={volume}")
        return True
    try:
        result = upbit.sell_market_order(ticker, volume)
        return bool(result and result.get("uuid"))
    except Exception as exc:
        print("[SELL ERROR]", exc)
        return False


def collect_holdings(cfg: StrategyConfig) -> dict[str, bool]:
    holdings = {}
    for ticker in cfg.target_coins:
        currency = ticker.split("-")[-1]
        holdings[ticker] = get_balance(currency) > 0.00001
    return holdings


def main():
    print("\n==============================")
    print("[START]", datetime.datetime.now())
    if DRY_RUN:
        print("[MODE] DRY_RUN — 주문 없이 신호만 확인")

    cfg = load_strategy_config()
    state = load_state()
    guard = PortfolioGuard(cfg, state)

    tickers = [t for t in cfg.position_priority if t in cfg.target_coins]
    tickers += [t for t in cfg.target_coins if t not in tickers]

    snapshots: dict[str, dict] = {}
    prices: dict[str, float] = {}

    # 1) 시장 데이터 수집
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

    holdings = collect_holdings(cfg)

    # 2) 매도 (보유 종목)
    for ticker in tickers:
        if ticker not in snapshots:
            continue
        if not holdings.get(ticker):
            continue

        currency = ticker.split("-")[-1]
        current_price = prices[ticker]
        market = snapshots[ticker]
        avg_buy_price = get_avg_buy_price(currency)
        coin_balance = get_balance(currency)

        do_sell, reason = get_sell_signal(
            current_price, avg_buy_price, market, state, ticker, cfg
        )
        if do_sell:
            if sell_coin(ticker, coin_balance):
                send_telegram(
                    f"[SELL] {currency}\nreason: {reason}\nprice: {current_price:,.0f}"
                )
                state["highest_price"].pop(ticker, None)
                holdings[ticker] = False

    # 3) 매수 후보
    holdings = collect_holdings(cfg)
    open_count = guard.open_position_count(holdings)
    buys_this_run = 0
    candidates = []

    for ticker in tickers:
        if ticker not in snapshots or holdings.get(ticker):
            continue
        market = snapshots[ticker]
        current_price = prices[ticker]
        if should_buy(current_price, market, cfg):
            candidates.append({"ticker": ticker, "market": market})

    for item in guard.sort_buy_candidates(candidates):
        ticker = item["ticker"]
        currency = ticker.split("-")[-1]
        market = item["market"]
        current_price = prices[ticker]

        krw = get_balance("KRW")
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

        if buy_coin(ticker, buy_amount, cfg):
            send_telegram(
                f"[BUY] {currency}\nmode: {market['mode']}\n"
                f"price: {current_price:,.0f}\nRSI: {market['rsi']:.1f} ADX: {market['adx']:.1f}"
            )
            guard.record_buy()
            open_count += 1
            buys_this_run += 1
            holdings[ticker] = True

    save_state(state)
    print(
        f"[END] open={guard.open_position_count(collect_holdings(cfg))} "
        f"daily_buys={guard.daily_buy_count}"
    )


if __name__ == "__main__":
    main()
