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
            profit_target, k_value, mode = 0.03, 0.5, "BULL"
        elif yesterday_return <= -5:
            profit_target, k_value, mode = 0.01, 0.7, "DEFENSE"
        else:
            profit_target, k_value, mode = 0.01, 0.5, "NORMAL"

        target_price = today["open"] + (yesterday["high"] - yesterday["low"]) * k_value

        return {
            "today_open": float(today["open"]),
            "prev_low": float(yesterday["low"]),
            "ma5": float(ma5),
            "target_price": float(target_price),
            "profit_target": profit_target,
            "mode": mode,
            "yesterday_return": yesterday_return,
        }
    except Exception as e:
        print(f"[일봉 조회 오류] {ticker} / {e}")
        return None


def is_order_success(result):
    if not isinstance(result, dict):
        print(f"[주문 응답 이상] {result}")
        return False
    if result.get("error"):
        print(f"[주문 실패] {result}")
        return False
    return bool(result.get("uuid"))


def buy_coin(ticker, amount_krw):
    try:
        result = upbit.buy_market_order(ticker, amount_krw * (1 - FEE_RATE))
        return is_order_success(result)
    except Exception as e:
        print(f"[매수 오류] {ticker} / {e}")
        return False


def sell_coin(ticker, volume):
    try:
        result = upbit.sell_market_order(ticker, volume)
        return is_order_success(result)
    except Exception as e:
        print(f"[매도 오류] {ticker} / {e}")
        return False


def main():
    if not ACCESS_KEY or not SECRET_KEY:
        raise RuntimeError("GitHub Secrets에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY를 등록하세요.")
    send_telegram_msg("✅ GitHub Actions 자동매매 봇 실행 확인")
    now = datetime.datetime.now()
    today = now.date().isoformat()
    state = load_state()

    if state.get("last_reset_date") != today:
        state = {"last_reset_date": today, "sold_today": {}}
        send_telegram_msg("📅 일일 전략 초기화 완료")

    balances = get_balances()

    for ticker in TARGET_COINS:
        currency = ticker.split("-")[-1]
        market = get_daily_data(ticker)
        current_price = get_current_price(ticker)

        if not market or current_price <= 0:
            continue

        coin_balance = get_balance(balances, currency)
        avg_buy_price = get_avg_buy_price(balances, currency)

        print(
            f"[{currency}] {market['mode']} / 현재가 {current_price:,.0f} / "
            f"목표가 {market['target_price']:,.0f} / MA5 {market['ma5']:,.0f}"
        )

        if coin_balance > 0.00001:
            if avg_buy_price <= 0:
                continue

            profit_rate = (current_price - avg_buy_price) / avg_buy_price
            sell_reason = ""

            if profit_rate >= market["profit_target"]:
                sell_reason = f"익절 {profit_rate * 100:.2f}%"
            elif profit_rate <= DEFAULT_STOP_LOSS:
                sell_reason = f"손절 {profit_rate * 100:.2f}%"
            elif current_price < market["prev_low"]:
                sell_reason = "전일 저점 이탈"

            if sell_reason and sell_coin(ticker, coin_balance):
                state["sold_today"][ticker] = True
                send_telegram_msg(
                    f"✅ [{currency}] 매도 완료\n"
                    f"사유: {sell_reason}\n"
                    f"매도가: {current_price:,.0f}원"
                )
            continue

        if state["sold_today"].get(ticker):
            print(f"[{currency}] 오늘 매도 완료 종목이라 재매수 스킵")
            continue

        if current_price > market["target_price"] and current_price > market["ma5"]:
            krw_balance = get_balance(balances, "KRW")
            buy_amount = min(BUY_AMOUNT_KRW, krw_balance)

            if buy_amount >= MIN_ORDER_KRW and buy_coin(ticker, buy_amount):
                send_telegram_msg(
                    f"🛒 [{currency}] 매수 완료\n"
                    f"현재가: {current_price:,.0f}원\n"
                    f"목표가: {market['target_price']:,.0f}원\n"
                    f"MA5: {market['ma5']:,.0f}원"
                )

    save_state(state)


if __name__ == "__main__":
    main()
