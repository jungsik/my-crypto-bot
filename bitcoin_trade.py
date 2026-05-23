import argparse
import datetime
import os
import time

import pyupbit
import requests


# =========================================================
# Upbit auto trading bot
# - BTC / ETH volatility breakout strategy
# - Backtest mode
# - Duplicate order guard
# - Safer API/order handling
# - Telegram notifications
# - MA5 trend filter
# - Reduced rate-limit pressure
# =========================================================


# =========================
# Environment variables
# =========================
ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


# =========================
# Settings
# =========================
TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000

DEFAULT_K = 0.5
DEFAULT_PROFIT_TARGET = 0.01
DEFAULT_STOP_LOSS = -0.02

LOOP_INTERVAL = 3
ORDER_COOLDOWN_SECONDS = 30
BALANCE_MIN_VOLUME = 0.00001
FEE_RATE = 0.0005


# =========================
# State
# =========================
buy_prices = {}
is_target_achieved = {}
today_profit_targets = {}
today_k_values = {}
last_order_at = {}

last_reset_date = None
upbit = None


def init_state(tickers):
    for ticker in tickers:
        buy_prices[ticker] = 0
        is_target_achieved[ticker] = False
        today_profit_targets[ticker] = DEFAULT_PROFIT_TARGET
        today_k_values[ticker] = DEFAULT_K
        last_order_at[ticker] = datetime.datetime.min


# =========================================================
# Telegram
# =========================================================
def send_telegram_msg(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[Telegram not configured]")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code != 200:
            print(f"[Telegram error] {response.text}")

    except Exception as e:
        print(f"[Telegram exception] {e}")


# =========================================================
# API helpers
# =========================================================
def get_current_price(ticker):
    try:
        price = pyupbit.get_current_price(ticker)
        return float(price) if price is not None else 0
    except Exception as e:
        print(f"[Current price error] {ticker} / {e}")
        return 0


def get_start_time(ticker):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
        if df is None or df.empty:
            return None
        return df.index[0]
    except Exception as e:
        print(f"[Start time error] {ticker} / {e}")
        return None


def get_all_balances():
    try:
        balances = upbit.get_balances()
        return balances if isinstance(balances, list) else []
    except Exception as e:
        print(f"[Balance error] {e}")
        return []


def get_balance_from_cache(balances, currency):
    try:
        for balance in balances:
            if balance.get("currency") == currency:
                return float(balance.get("balance", 0) or 0)
        return 0
    except Exception:
        return 0


def get_avg_buy_price_from_cache(balances, currency):
    try:
        for balance in balances:
            if balance.get("currency") == currency:
                return float(balance.get("avg_buy_price", 0) or 0)
        return 0
    except Exception:
        return 0


def get_daily_market_data(ticker, k):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=6)
        if df is None or len(df) < 6:
            return None

        today = df.iloc[-1]
        yesterday = df.iloc[-2]
        ma5 = df["close"].iloc[-6:-1].mean()
        target_price = today["open"] + (yesterday["high"] - yesterday["low"]) * k

        return {
            "target_price": float(target_price),
            "today_open": float(today["open"]),
            "prev_low": float(yesterday["low"]),
            "ma5": float(ma5),
            "yesterday_open": float(yesterday["open"]),
            "yesterday_close": float(yesterday["close"]),
        }
    except Exception as e:
        print(f"[Daily market data error] {ticker} / {e}")
        return None


# =========================================================
# Strategy policy
# =========================================================
def set_policy_from_yesterday(ticker, yesterday_open, yesterday_close, notify=True):
    try:
        if yesterday_open <= 0:
            return

        yesterday_return_pct = ((yesterday_close - yesterday_open) / yesterday_open) * 100
        coin_name = ticker.split("-")[-1]

        if yesterday_return_pct >= 8:
            today_profit_targets[ticker] = 0.03
            today_k_values[ticker] = 0.5
            msg = (
                f"[{coin_name}] bull mode\n"
                f"Yesterday return: {yesterday_return_pct:.2f}%\n"
                f"Take profit: 3%"
            )
        elif yesterday_return_pct <= -5:
            today_profit_targets[ticker] = 0.01
            today_k_values[ticker] = 0.7
            msg = (
                f"[{coin_name}] defense mode\n"
                f"Yesterday return: {yesterday_return_pct:.2f}%\n"
                f"K: 0.7"
            )
        else:
            today_profit_targets[ticker] = 0.01
            today_k_values[ticker] = 0.5
            msg = (
                f"[{coin_name}] normal mode\n"
                f"Yesterday return: {yesterday_return_pct:.2f}%"
            )

        print(msg)
        if notify:
            send_telegram_msg(msg)

    except Exception as e:
        print(f"[Policy error] {ticker} / {e}")


def is_order_cooldown_finished(ticker):
    elapsed = datetime.datetime.now() - last_order_at[ticker]
    return elapsed.total_seconds() >= ORDER_COOLDOWN_SECONDS


def mark_order_time(ticker):
    last_order_at[ticker] = datetime.datetime.now()


# =========================================================
# Order helpers
# =========================================================
def is_successful_order(result):
    if not isinstance(result, dict):
        return False
    if result.get("error"):
        return False
    return bool(result.get("uuid"))


def buy_coin(ticker, amount_krw):
    try:
        if amount_krw < MIN_ORDER_KRW:
            return False

        result = upbit.buy_market_order(ticker, amount_krw * (1 - FEE_RATE))
        if is_successful_order(result):
            mark_order_time(ticker)
            return True

        print(f"[Buy rejected] {ticker} / {result}")
        return False
    except Exception as e:
        print(f"[Buy error] {ticker} / {e}")
        return False


def sell_coin(ticker, volume):
    try:
        if volume <= BALANCE_MIN_VOLUME:
            return False

        result = upbit.sell_market_order(ticker, volume)
        if is_successful_order(result):
            mark_order_time(ticker)
            return True

        print(f"[Sell rejected] {ticker} / {result}")
        return False
    except Exception as e:
        print(f"[Sell error] {ticker} / {e}")
        return False


# =========================================================
# Live trading
# =========================================================
def run_live(tickers):
    global last_reset_date, upbit

    if not ACCESS_KEY or not SECRET_KEY:
        raise RuntimeError("UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY are required for live mode.")

    upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)
    init_state(tickers)

    start_msg = "Upbit auto trading bot started\nStrategy: volatility breakout + MA5 filter"
    print(start_msg)
    send_telegram_msg(start_msg)

    while True:
        try:
            now = datetime.datetime.now()
            start_time = get_start_time("KRW-BTC")

            if start_time is None:
                time.sleep(LOOP_INTERVAL)
                continue

            end_time = start_time + datetime.timedelta(days=1)
            today = now.date()

            market_data_by_ticker = {}
            for ticker in tickers:
                market_data = get_daily_market_data(ticker, today_k_values.get(ticker, DEFAULT_K))
                if market_data is not None:
                    market_data_by_ticker[ticker] = market_data
                time.sleep(0.12)

            if last_reset_date != today:
                last_reset_date = today
                print("[Daily reset]")
