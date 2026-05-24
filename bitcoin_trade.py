import datetime
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyupbit
import requests

# =========================================================
# 업비트 멀티 레짐 자동매매 봇 (설정 연동 완료)
# =========================================================

ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not ACCESS_KEY or not SECRET_KEY:
    raise RuntimeError("UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 환경변수 확인 필요")

# =========================================================
# 기본 설정값 (strategy_config.json에서 덮어씌워짐)
# =========================================================

TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE"]

BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000
INTERVAL = "minute15"
FEE_RATE = 0.0005

RSI_MIN = 48
RSI_MAX = 72
VOLUME_MULTIPLIER = 1.3
MAX_CHASE_RATE = 0.003
ADX_MIN = 20
ATR_STOP_MULTIPLIER = 1.3
ATR_PROFIT_MULTIPLIER = 2.2
TRAILING_START = 0.004
TRAILING_DROP = 0.0025
BBANDS_PERIOD = 20
BBANDS_STD = 2
SIDEWAYS_RSI_BUY = 35

STATE_FILE = Path("bot_state.json")
STRATEGY_CONFIG_FILE = Path("strategy_config.json")

upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)

# =========================================================
# 설정 파일 로드
# =========================================================

def load_strategy_config():
    global RSI_MIN, RSI_MAX, VOLUME_MULTIPLIER, MAX_CHASE_RATE
    global ADX_MIN, ATR_STOP_MULTIPLIER, ATR_PROFIT_MULTIPLIER
    global TRAILING_START, TRAILING_DROP, SIDEWAYS_RSI_BUY
    global BBANDS_PERIOD, BBANDS_STD

    if not STRATEGY_CONFIG_FILE.exists():
        print("[CONFIG] strategy_config.json 파일을 찾을 수 없어 기본값을 사용합니다.")
        return

    try:
        config = json.loads(STRATEGY_CONFIG_FILE.read_text(encoding="utf-8"))
        RSI_MIN = config.get("RSI_MIN", RSI_MIN)
        RSI_MAX = config.get("RSI_MAX", RSI_MAX)
        VOLUME_MULTIPLIER = config.get("VOLUME_MULTIPLIER", VOLUME_MULTIPLIER)
        MAX_CHASE_RATE = config.get("MAX_CHASE_RATE", MAX_CHASE_RATE)
        ADX_MIN = config.get("ADX_MIN", ADX_MIN)
        ATR_STOP_MULTIPLIER = config.get("ATR_STOP_MULTIPLIER", ATR_STOP_MULTIPLIER)
        ATR_PROFIT_MULTIPLIER = config.get("ATR_PROFIT_MULTIPLIER", ATR_PROFIT_MULTIPLIER)
        TRAILING_START = config.get("TRAILING_START", TRAILING_START)
        TRAILING_DROP = config.get("TRAILING_DROP", TRAILING_DROP)
        SIDEWAYS_RSI_BUY = config.get("SIDEWAYS_RSI_BUY", SIDEWAYS_RSI_BUY)
        BBANDS_PERIOD = config.get("BBANDS_PERIOD", BBANDS_PERIOD)
        BBANDS_STD = config.get("BBANDS_STD", BBANDS_STD)

        print("[CONFIG] 성공적으로 최적화 설정(strategy_config.json)을 불러왔습니다.")
    except Exception as e:
        print("[CONFIG LOAD ERROR]", e)

# =========================================================
# 텔레그램 및 상태 저장
# =========================================================

def send_telegram(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TELEGRAM DISABLED]\n", message)
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as e:
        print("[TELEGRAM ERROR]", e)

def load_state():
    if not STATE_FILE.exists():
        return {"highest_price": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"highest_price": {}}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

# =========================================================
# 지표 계산 (RSI, ATR, ADX, BB)
# =========================================================

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    value = float(rsi.iloc[-1])
    return 50 if np.isnan(value) else value

def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    value = float(atr.iloc[-1])
    return 0 if np.isnan(value) else value

def calculate_adx(df, period=14):
    plus_dm = df["high"].diff()
    minus_dm = df["low"].diff() * -1
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    di_sum = plus_di + minus_di
    dx = np.where(di_sum == 0, 0, ((plus_di - minus_di).abs() / di_sum) * 100)
    
    adx = pd.Series(dx, index=df.index).rolling(period).mean()
    value = float(adx.iloc[-1])
    return 0 if np.isnan(value) else value

def calculate_bollinger(close, period=BBANDS_PERIOD, std_dev=BBANDS_STD):
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
# 시장 데이터 분석
# =========================================================

def get_market_data(ticker):
    try:
        df = pyupbit.get_ohlcv(ticker, interval=INTERVAL, count=100)
        if df is None or len(df) < 30:
            return None

        current = df.iloc[-1]
        prev = df.iloc[-2]
        close = df["close"]

        ma5 = float(close.iloc[-6:-1].mean())
        ma10 = float(close.iloc[-11:-1].mean())
        ma20 = float(close.iloc[-21:-1].mean())

        rsi = calculate_rsi(close.iloc[:-1])
        adx = calculate_adx(df)
        atr = calculate_atr(df)
        bb = calculate_bollinger(close)

        avg_volume5 = float(df["volume"].iloc[-6:-1].mean())
        recent_return = ((prev["close"] - prev["open"]) / prev["open"]) * 100

        # 시장 모드 분류
        if adx >= ADX_MIN and ma5 > ma10 and recent_return >= -0.3:
            mode = "TREND"
        elif adx < ADX_MIN:
            mode = "SIDEWAYS"
        else:
            mode = "DEFENSE"

        target_price = max(
            float(prev["high"]),
            float(current["open"] + ((prev["high"] - prev["low"]) * 0.25)),
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
            "today_volume": float(current["volume"]),
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
# 매수 / 매도 조건 
# =========================================================

def should_buy(ticker, current_price, market):
    try:
        if market["rsi"] >= RSI_MAX:
            return False

        if market["mode"] == "TREND":
            breakout = current_price > market["target_price"]
            uptrend = market["ma5"] > market["ma10"] and current_price > market["ma20"]
            volume_ok = market["today_volume"] > market["avg_volume5"] * VOLUME_MULTIPLIER
            chase_ok = current_price < market["target_price"] * (1 + MAX_CHASE_RATE)
            return breakout and uptrend and volume_ok and chase_ok

        if market["mode"] == "SIDEWAYS":
            near_lower = current_price <= market["bb_lower"] * 1.01
            rsi_ok = market["rsi"] <= SIDEWAYS_RSI_BUY
            return near_lower and rsi_ok

        return False
    except Exception as e:
        print("[BUY CHECK ERROR]", e)
        return False

def get_sell_signal(ticker, current_price, avg_buy_price, market, state):
    try:
        if avg_buy_price <= 0:
            return False, ""

        atr_stop = market["atr"] * ATR_STOP_MULTIPLIER
        atr_target = market["atr"] * ATR_PROFIT_MULTIPLIER
        highest = max(state["highest_price"].get(ticker, 0), current_price)
        state["highest_price"][ticker] = highest

        trailing_drop = (current_price - highest) / highest
        profit_rate = (current_price - avg_buy_price) / avg_buy_price

        if current_price >= avg_buy_price + atr_target:
            return True, "ATR TAKE PROFIT"
        if current_price <= avg_buy_price - atr_stop:
            return True, "ATR STOP LOSS"
        if profit_rate >= TRAILING_START and trailing_drop <= -TRAILING_DROP:
            return True, "TRAILING STOP"
        if current_price < market["prev_low"]:
            return True, "BREAK PREVIOUS LOW"

        return False, ""
    except Exception as e:
        print("[SELL SIGNAL ERROR]", e)
        return False, ""

# =========================================================
# 주문 헬퍼
# =========================================================

def get_balance(currency):
    try:
        for item in upbit.get_balances():
            if item["currency"] == currency:
                return float(item["balance"] or 0)
        return 0
    except Exception:
        return 0

def get_avg_buy_price(currency):
    try:
        for item in upbit.get_balances():
            if item["currency"] == currency:
                return float(item["avg_buy_price"] or 0)
        return 0
    except Exception:
        return 0

def buy_coin(ticker, amount):
    try:
        result = upbit.buy_market_order(ticker, amount * (1 - FEE_RATE))
        return bool(result.get("uuid"))
    except Exception as e:
        print("[BUY ERROR]", e)
        return False

def sell_coin(ticker, volume):
    try:
        result = upbit.sell_market_order(ticker, volume)
        return bool(result.get("uuid"))
    except Exception as e:
        print("[SELL ERROR]", e)
        return False

# =========================================================
# 메인 로직
# =========================================================

def main():
    print("\n==============================")
    print("[START]", datetime.datetime.now())

    load_strategy_config() # 봇 시작 시 전략 설정 적용
    state = load_state()

    for ticker in TARGET_COINS:
        try:
            currency = ticker.split("-")[-1]
            market = get_market_data(ticker)
            if not market:
                continue

            current_price = pyupbit.get_current_price(ticker)
            if not current_price:
                continue

            print(f"[{currency}] mode={market['mode']} price={current_price:,.0f} RSI={market['rsi']:.1f} ADX={market['adx']:.1f}")

            coin_balance = get_balance(currency)
            holding = coin_balance > 0.00001

            # 매도 로직
            if holding:
                avg_buy_price = get_avg_buy_price(currency)
                should_sell, reason = get_sell_signal(ticker, current_price, avg_buy_price, market, state)
                
                if should_sell:
                    if sell_coin(ticker, coin_balance):
                        send_telegram(f"[SELL] {currency}\nreason: {reason}\nprice: {current_price:,.0f}")
                        state["highest_price"].pop(ticker, None)
                continue

            # 매수 로직
            if should_buy(ticker, current_price, market):
                krw = get_balance("KRW")
                buy_amount = min(BUY_AMOUNT_KRW, krw)
                if buy_amount >= MIN_ORDER_KRW:
                    if buy_coin(ticker, buy_amount):
                        send_telegram(f"[BUY] {currency}\nmode: {market['mode']}\nprice: {current_price:,.0f}\nRSI: {market['rsi']:.1f}\nADX: {market['adx']:.1f}")

            time.sleep(0.2)
        except Exception as e:
            print("[MAIN LOOP ERROR]", ticker, e)

    save_state(state)
    print("[END]")

if __name__ == "__main__":
    main()
