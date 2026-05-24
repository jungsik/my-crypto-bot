import datetime
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyupbit
import requests

# =========================================================
# 업비트 멀티 레짐 자동매매 봇
# - 추세장: 돌파 추종
# - 횡보장: RSI 반등
# - ATR 손절/익절
# - ADX 추세강도 필터
# - 볼린저밴드 전략
# - 텔레그램 알림
# =========================================================

ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TARGET_COINS = [
    "KRW-BTC",
    "KRW-ETH",
    "KRW-SOL",
    "KRW-XRP",
    "KRW-DOGE",
]

BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000

INTERVAL = "minute15"

FEE_RATE = 0.0005

RSI_MIN = 48
RSI_MAX = 72

VOLUME_MULTIPLIER = 1.3
MAX_CHASE_RATE = 0.003

ADX_MIN = 22

ATR_STOP_MULTIPLIER = 1.3
ATR_PROFIT_MULTIPLIER = 2.2

TRAILING_START = 0.004
TRAILING_DROP = 0.0025

BBANDS_PERIOD = 20
BBANDS_STD = 2

SIDEWAYS_RSI_BUY = 35

STATE_FILE = Path("bot_state.json")

upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)


# =========================================================
# 텔레그램
# =========================================================

def send_telegram(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print(message)
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

    except Exception as e:
        print("[TELEGRAM ERROR]", e)


# =========================================================
# 상태 저장
# =========================================================

def load_state():
    if not STATE_FILE.exists():
        return {
            "highest_price": {},
        }

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

    except Exception:
        return {
            "highest_price": {},
        }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# =========================================================
# 보조지표
# =========================================================

def calculate_rsi(close, period=14):
    delta = close.diff()

    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()

    rs = gain / loss

    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])


def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]

    high_close = np.abs(
        df["high"] - df["close"].shift()
    )

    low_close = np.abs(
        df["low"] - df["close"].shift()
    )

    tr = pd.concat(
        [
            high_low,
            high_close,
            low_close,
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean()

    return float(atr.iloc[-1])


def calculate_adx(df, period=14):
    plus_dm = df["high"].diff()
    minus_dm = df["low"].diff() * -1

    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr1 = df["high"] - df["low"]

    tr2 = (
        df["high"] - df["close"].shift()
    ).abs()

    tr3 = (
        df["low"] - df["close"].shift()
    ).abs()

    tr = pd.concat(
        [
            tr1,
            tr2,
            tr3,
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean()

    plus_di = (
        100
        * (
            plus_dm.rolling(period).mean()
            / atr
        )
    )

    minus_di = (
        100
        * (
            minus_dm.rolling(period).mean()
            / atr
        )
    )

    dx = (
        (plus_di - minus_di).abs()
        / (plus_di + minus_di)
    ) * 100

    adx = dx.rolling(period).mean()

    return float(adx.iloc[-1])


def calculate_bollinger(
    close,
    period=20,
    std_dev=2,
):
    ma = close.rolling(period).mean()

    std = close.rolling(period).std()

    upper = ma + (std * std_dev)

    lower = ma - (std * std_dev)

    return {
        "upper": float(upper.iloc[-1]),
        "middle": float(ma.iloc[-1]),
        "lower": float(lower.iloc[-1]),
    }


# =========================================================
# 시장 데이터
# =========================================================

def get_market_data(ticker):
    try:
        df = pyupbit.get_ohlcv(
            ticker,
            interval=INTERVAL,
            count=100,
        )

        if df is None or len(df) < 30:
            return None

        current = df.iloc[-1]
        prev = df.iloc[-2]

        close = df["close"]

        ma5 = float(
            close.iloc[-6:-1].mean()
        )

        ma10 = float(
            close.iloc[-11:-1].mean()
        )

        ma20 = float(
            close.iloc[-21:-1].mean()
        )

        rsi = calculate_rsi(close.iloc[:-1])

        adx = calculate_adx(df)

        atr = calculate_atr(df)

        bb = calculate_bollinger(close)

        avg_volume5 = float(
            df["volume"].iloc[-6:-1].mean()
        )

        recent_return = (
            (
                prev["close"]
                - prev["open"]
            )
            / prev["open"]
        ) * 100

        if (
            adx >= ADX_MIN
            and ma5 > ma10
            and recent_return >= 0
        ):
            mode = "TREND"

        elif adx < ADX_MIN:
            mode = "SIDEWAYS"

        else:
            mode = "DEFENSE"

        target_price = max(
            float(prev["high"]),
            float(
                current["open"]
                + (
                    (
                        prev["high"]
                        - prev["low"]
                    )
                    * 0.25
                )
            ),
        )

        return {
            "mode": mode,
            "target_price": target_price,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "rsi": rsi,
            "adx": adx,
            "atr": atr,
            "today_volume": float(
                current["volume"]
            ),
            "avg_volume5": avg_volume5,
            "prev_low": float(prev["low"]),
            "bb_upper": bb["upper"],
            "bb_middle": bb["middle"],
            "bb_lower": bb["lower"],
        }

    except Exception as e:
        print("[MARKET ERROR]", ticker, e)
        return None


# =========================================================
# 매수 조건
# =========================================================

def should_buy(current_price, market):

    if market["rsi"] >= 78:
        return False

    # 추세장
    if market["mode"] == "TREND":

        breakout = (
            current_price
            > market["target_price"]
        )

        uptrend = (
            market["ma5"]
            > market["ma10"]
            and current_price
            > market["ma20"]
        )

        volume_ok = (
            market["today_volume"]
            > market["avg_volume5"]
            * VOLUME_MULTIPLIER
        )

        chase_ok = (
            current_price
            < market["target_price"]
            * (1 + MAX_CHASE_RATE)
        )

        return (
            breakout
            and uptrend
            and volume_ok
            and chase_ok
        )

    # 횡보장
    if market["mode"] == "SIDEWAYS":

        near_lower = (
            current_price
            <= market["bb_lower"] * 1.01
        )

        rsi_ok = (
            market["rsi"]
            <= SIDEWAYS_RSI_BUY
        )

        return near_lower and rsi_ok

    return False


# =========================================================
# 매도 조건
# =========================================================

def get_sell_signal(
    ticker,
    current_price,
    avg_buy_price,
    market,
    state,
):

    if avg_buy_price <= 0:
        return False, ""

    atr_stop = (
        market["atr"]
        * ATR_STOP_MULTIPLIER
    )

    atr_target = (
        market["atr"]
        * ATR_PROFIT_MULTIPLIER
    )

    highest = max(
        state["highest_price"].get(
            ticker,
            0,
        ),
        current_price,
    )

    state["highest_price"][ticker] = highest

    trailing_drop = (
        current_price - highest
    ) / highest

    profit_rate = (
        current_price
        - avg_buy_price
    ) / avg_buy_price

    # ATR 익절
    if (
        current_price
        >= avg_buy_price + atr_target
    ):
        return True, "ATR TAKE PROFIT"

    # ATR 손절
    if (
        current_price
        <= avg_buy_price - atr_stop
    ):
        return True, "ATR STOP LOSS"

    # 트레일링
    if (
        profit_rate >= TRAILING_START
        and trailing_drop <= -TRAILING_DROP
    ):
        return True, "TRAILING STOP"

    # 전일 저점 이탈
    if current_price < market["prev_low"]:
        return True, "BREAK PREVIOUS LOW"

    return False, ""


# =========================================================
# 잔고
# =========================================================

def get_balance(currency):
    try:
        balances = upbit.get_balances()

        for item in balances:

            if item["currency"] == currency:
                return float(
                    item["balance"]
                    or 0
                )

        return 0

    except Exception as e:
        print("[BALANCE ERROR]", e)
        return 0


def get_avg_buy_price(currency):
    try:
        balances = upbit.get_balances()

        for item in balances:

            if item["currency"] == currency:
                return float(
                    item["avg_buy_price"]
                    or 0
                )

        return 0

    except Exception:
        return 0


# =========================================================
# 주문
# =========================================================

def buy_coin(ticker, amount):
    try:
        result = upbit.buy_market_order(
            ticker,
            amount * (1 - FEE_RATE),
        )

        return bool(result.get("uuid"))

    except Exception as e:
        print("[BUY ERROR]", e)
        return False


def sell_coin(ticker, volume):
    try:
        result = upbit.sell_market_order(
            ticker,
            volume,
        )

        return bool(result.get("uuid"))

    except Exception as e:
        print("[SELL ERROR]", e)
        return False


# =========================================================
# 메인
# =========================================================

def main():

    state = load_state()

    for ticker in TARGET_COINS:

        currency = ticker.split("-")[-1]

        market = get_market_data(ticker)

        if not market:
            continue

        current_price = pyupbit.get_current_price(
            ticker
        )

        if not current_price:
            continue

        print(
            f"[{currency}] "
            f"mode={market['mode']} "
            f"price={current_price:,.0f} "
            f"RSI={market['rsi']:.1f} "
            f"ADX={market['adx']:.1f}"
        )

        coin_balance = get_balance(currency)

        holding = coin_balance > 0.00001

        # =========================
        # 매도
        # =========================

        if holding:

            avg_buy_price = get_avg_buy_price(
                currency
            )

            should_sell, reason = (
                get_sell_signal(
                    ticker,
                    current_price,
                    avg_buy_price,
                    market,
                    state,
                )
            )

            if should_sell:

                success = sell_coin(
                    ticker,
                    coin_balance,
                )

                if success:

                    send_telegram(
                        f"[SELL] {currency}\n"
                        f"reason: {reason}\n"
                        f"price: {current_price:,.0f}"
                    )

                    state["highest_price"].pop(
                        ticker,
                        None,
                    )

            continue

        # =========================
        # 매수
        # =========================

        if not should_buy(
            current_price,
            market,
        ):
            continue

        krw = get_balance("KRW")

        buy_amount = min(
            BUY_AMOUNT_KRW,
            krw,
        )

        if buy_amount < MIN_ORDER_KRW:
            continue

        success = buy_coin(
            ticker,
            buy_amount,
        )

        if success:

            send_telegram(
                f"[BUY] {currency}\n"
                f"mode: {market['mode']}\n"
                f"price: {current_price:,.0f}\n"
                f"RSI: {market['rsi']:.1f}\n"
                f"ADX: {market['adx']:.1f}"
            )

    save_state(state)


if __name__ == "__main__":
    main()
    
