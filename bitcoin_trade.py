import datetime
import json
import os
from pathlib import Path

import pyupbit
import requests


ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TARGET_COINS = ["KRW-BTC", "KRW-ETH"]
BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000
DEFAULT_K = 0.5
DEFAULT_PROFIT_TARGET = 0.01
DEFAULT_STOP_LOSS = -0.02
FEE_RATE = 0.0005
STATE_FILE = Path("bot_state.json")

upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)


def send_telegram_msg(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[텔레그램 미설정]", message)
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
    except Exception as e:
        print(f"[텔레그램 오류] {e}")


def load_state():
    if not STATE_FILE.exists():
        return {"last_reset_date": "", "sold_today": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_reset_date": "", "sold_today": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_balances():
    try:
        balances = upbit.get_balances()
        return balances if isinstance(balances, list) else []
    except Exception as e:
        print(f"[잔고 조회 오류] {e}")
        return []


def get_balance(balances, currency):
    for item in balances:
        if item.get("currency") == currency:
            return float(item.get("balance", 0) or 0)
    return 0


def get_avg_buy_price(balances, currency):
    for item in balances:
        if item.get("currency") == currency:
            return float(item.get("avg_buy_price", 0) or 0)
    return 0


def get_current_price(ticker):
    try:
        price = pyupbit.get_current_price(ticker)
        return float(price) if price else 0
    except Exception as e:
        print(f"[현재가 오류] {ticker} / {e}")
        return 0


def get_daily_data(ticker):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=6)
        if df is None or len(df) < 6:
            return None

        today = df.iloc[-1]
        yesterday = df.iloc[-2]
        ma5 = df["close"].iloc[-6:-1].mean()
        yesterday_return = (yesterday["close"] - yesterday["open"]) / yesterday["open"] * 100

        if yesterday_return >= 8:
            profit_target, k_value, mode = 0.03, 0.5, "불장"
        elif yesterday_return <= -5:
