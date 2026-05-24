import datetime
import json
import os
from pathlib import Path

import pyupbit
import requests


# =========================================================
# GitHub Actions용 업비트 자동매매 봇
# - 5분마다 1회 실행 후 종료
# - BTC / ETH 기본 설정
# - 변동성 돌파 + MA 추세 + RSI + 거래량 + 추격매수 방지
# =========================================================

ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000

DEFAULT_K = 0.5
DEFENSE_K = 0.7

NORMAL_PROFIT_TARGET = 0.01
BULL_PROFIT_TARGET = 0.03
STOP_LOSS = -0.02
HARD_PROFIT_TARGET = 0.015
TRAILING_START = 0.006
TRAILING_DROP = 0.0045

FEE_RATE = 0.0005
STATE_FILE = Path("bot_state.json")
STRATEGY_CONFIG_FILE = Path("strategy_config.json")

RSI_MIN = 50
RSI_MAX = 75
VOLUME_MULTIPLIER = 1.2
MAX_CHASE_RATE = 0.01


upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)


def load_strategy_config():
    global RSI_MIN, RSI_MAX, VOLUME_MULTIPLIER, MAX_CHASE_RATE

    if not STRATEGY_CONFIG_FILE.exists():
        print("[CONFIG] strategy_config.json not found. Use default values.")
        return

    try:
        config = json.loads(STRATEGY_CONFIG_FILE.read_text(encoding="utf-8"))
        RSI_MIN = int(config.get("RSI_MIN", RSI_MIN))
        RSI_MAX = int(config.get("RSI_MAX", RSI_MAX))
        VOLUME_MULTIPLIER = float(
            config.get("VOLUME_MULTIPLIER", VOLUME_MULTIPLIER)
        )
        MAX_CHASE_RATE = float(config.get("MAX_CHASE_RATE", MAX_CHASE_RATE))

        print(
            "[CONFIG] loaded "
            f"RSI={RSI_MIN}~{RSI_MAX}, "
            f"VOLx={VOLUME_MULTIPLIER}, "
            f"CHASE={MAX_CHASE_RATE}"
        )
    except Exception as e:
        print("[CONFIG LOAD ERROR]", e)


def send_telegram_msg(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TELEGRAM SKIP]", message)
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )

        if response.status_code != 200:
            print("[TELEGRAM ERROR]", response.status_code, response.text)

    except Exception as e:
        print("[TELEGRAM EXCEPTION]", e)


def load_state():
    if not STATE_FILE.exists():
        return {"last_reset_date": "", "sold_today": {}, "highest_price": {}}

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state.setdefault("sold_today", {})
        state.setdefault("highest_price", {})
        return state
    except Exception as e:
        print("[STATE LOAD ERROR]", e)
        return {"last_reset_date": "", "sold_today": {}, "highest_price": {}}


def save_state(state):
    try:
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print("[STATE SAVE ERROR]", e)


def get_balances():
    try:
        balances = upbit.get_balances()
        return balances if isinstance(balances, list) else []
    except Exception as e:
        print("[BALANCE ERROR]", e)
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
        print("[PRICE ERROR]", ticker, e)
        return 0


def calculate_rsi(close_series, period=14):
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def get_market_data(ticker):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=30)

        if df is None or len(df) < 21:
            print("[DATA SKIP]", ticker, "not enough candle data")
            return None

        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        close = df["close"]
        volume = df["volume"]

        ma5 = float(close.iloc[-6:-1].mean())
        ma10 = float(close.iloc[-11:-1].mean())
        ma20 = float(close.iloc[-21:-1].mean())
        rsi = calculate_rsi(close.iloc[:-1], 14)
        avg_volume5 = float(volume.iloc[-6:-1].mean())
        today_volume = float(today["volume"])

        yesterday_return = (
            (yesterday["close"] - yesterday["open"]) / yesterday["open"]
        ) * 100

        if yesterday_return >= 8:
            mode = "BULL"
            k_value = DEFAULT_K
            profit_target = BULL_PROFIT_TARGET
        elif yesterday_return <= -5:
            mode = "DEFENSE"
            k_value = DEFENSE_K
            profit_target = NORMAL_PROFIT_TARGET
        else:
            mode = "NORMAL"
            k_value = DEFAULT_K
            profit_target = NORMAL_PROFIT_TARGET

        target_price = today["open"] + (
            yesterday["high"] - yesterday["low"]
        ) * k_value

        return {
            "mode": mode,
            "today_open": float(today["open"]),
            "prev_low": float(yesterday["low"]),
            "target_price": float(target_price),
            "profit_target": profit_target,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "rsi": rsi,
            "today_volume": today_volume,
            "avg_volume5": avg_volume5,
            "yesterday_return": float(yesterday_return),
        }

    except Exception as e:
        print("[MARKET DATA ERROR]", ticker, e)
        return None


def is_order_success(result):
    if not isinstance(result, dict):
        print("[ORDER RESPONSE ERROR]", result)
        return False

    if result.get("error"):
        print("[ORDER FAILED]", result)
        return False

    return bool(result.get("uuid"))


def buy_coin(ticker, amount_krw):
    try:
        result = upbit.buy_market_order(ticker, amount_krw * (1 - FEE_RATE))
        return is_order_success(result)
    except Exception as e:
        print("[BUY ERROR]", ticker, e)
        return False


def sell_coin(ticker, volume):
    try:
        result = upbit.sell_market_order(ticker, volume)
        return is_order_success(result)
    except Exception as e:
        print("[SELL ERROR]", ticker, e)
        return False


def should_buy(current_price, market):
    breakout = current_price > market["target_price"]
    uptrend = market["ma5"] > market["ma10"] > market["ma20"]
    rsi_ok = RSI_MIN <= market["rsi"] <= RSI_MAX
    volume_ok = market["today_volume"] > market["avg_volume5"] * VOLUME_MULTIPLIER
    chase_ok = current_price < market["target_price"] * (1 + MAX_CHASE_RATE)

    return {
        "result": breakout and uptrend and rsi_ok and volume_ok and chase_ok,
        "breakout": breakout,
        "uptrend": uptrend,
        "rsi_ok": rsi_ok,
        "volume_ok": volume_ok,
        "chase_ok": chase_ok,
    }


def get_sell_reason(ticker, current_price, avg_buy_price, market, state):
    if avg_buy_price <= 0:
        return "", 0

    profit_rate = (current_price - avg_buy_price) / avg_buy_price
    highest_price = float(state["highest_price"].get(ticker, 0) or 0)
    highest_price = max(highest_price, current_price)
    state["highest_price"][ticker] = highest_price
    trailing_drop_rate = (current_price - highest_price) / highest_price

    if profit_rate >= HARD_PROFIT_TARGET:
        return f"FAST PROFIT {profit_rate * 100:.2f}%", profit_rate

    if profit_rate >= TRAILING_START and trailing_drop_rate <= -TRAILING_DROP:
        return (
            f"TRAILING STOP profit={profit_rate * 100:.2f}% "
            f"drop={trailing_drop_rate * 100:.2f}%",
            profit_rate,
        )

    if profit_rate >= market["profit_target"] and market["rsi"] >= RSI_MAX:
        return f"RSI PROFIT {profit_rate * 100:.2f}%", profit_rate

    if profit_rate <= STOP_LOSS:
        return f"STOP LOSS {profit_rate * 100:.2f}%", profit_rate

    if current_price < market["prev_low"]:
        return "BREAK PREVIOUS LOW", profit_rate

    return "", profit_rate


def print_market_log(currency, current_price, market, signal):
    print(
        f"[{currency}] mode={market['mode']} "
        f"price={current_price:,.0f} "
        f"target={market['target_price']:,.0f} "
        f"ma5={market['ma5']:,.0f} "
        f"ma10={market['ma10']:,.0f} "
        f"ma20={market['ma20']:,.0f} "
        f"rsi={market['rsi']:.1f} "
        f"vol={market['today_volume']:.0f}/{market['avg_volume5']:.0f} "
        f"signal={signal}"
    )


def format_bool(value):
    return "OK" if value else "NO"


def build_status_line(
    ticker,
    currency,
    current_price,
    market,
    signal,
    holding,
    profit_rate,
    state,
):
    holding_text = "HOLD" if holding else "NONE"
    profit_text = f"{profit_rate * 100:.2f}%" if holding else "-"
    highest_price = float(state.get("highest_price", {}).get(ticker, 0) or 0)
    high_text = f"{highest_price:,.0f}" if holding and highest_price > 0 else "-"

    return (
        f"{currency} {market['mode']} {holding_text}\n"
        f"price {current_price:,.0f} / target {market['target_price']:,.0f}\n"
        f"MA {market['ma5']:,.0f}>{market['ma10']:,.0f}>{market['ma20']:,.0f} "
        f"({format_bool(signal['uptrend'])}) / RSI {market['rsi']:.1f} "
        f"({format_bool(signal['rsi_ok'])})\n"
        f"VOL {market['today_volume']:.0f}/{market['avg_volume5']:.0f} "
        f"({format_bool(signal['volume_ok'])}) / breakout "
        f"{format_bool(signal['breakout'])} / chase {format_bool(signal['chase_ok'])}\n"
        f"buy_signal {format_bool(signal['result'])} / profit {profit_text} "
        f"/ high {high_text}"
    )


def main():
    if not ACCESS_KEY or not SECRET_KEY:
        raise RuntimeError("Set UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY in GitHub Secrets.")

    load_strategy_config()

    now = datetime.datetime.now()
    today = now.date().isoformat()
    state = load_state()

    if state.get("last_reset_date") != today:
        state = {"last_reset_date": today, "sold_today": {}, "highest_price": {}}
        send_telegram_msg("Daily strategy reset completed")

    balances = get_balances()
    status_lines = []

    for ticker in TARGET_COINS:
        currency = ticker.split("-")[-1]
        market = get_market_data(ticker)
        current_price = get_current_price(ticker)

        if not market or current_price <= 0:
            continue

        signal = should_buy(current_price, market)
        print_market_log(currency, current_price, market, signal)

        coin_balance = get_balance(balances, currency)
        avg_buy_price = get_avg_buy_price(balances, currency)
        holding = coin_balance > 0.00001
        profit_rate = 0

        if holding and avg_buy_price > 0:
            profit_rate = (current_price - avg_buy_price) / avg_buy_price

        status_lines.append(
            build_status_line(
                ticker,
                currency,
                current_price,
                market,
                signal,
                holding,
                profit_rate,
                state,
            )
        )

        if holding:
            sell_reason, profit_rate = get_sell_reason(
                ticker,
                current_price,
                avg_buy_price,
                market,
                state,
            )

            if sell_reason and sell_coin(ticker, coin_balance):
                state["sold_today"][ticker] = True
                state["highest_price"].pop(ticker, None)
                send_telegram_msg(
                    f"[{currency}] SELL DONE\n"
                    f"reason: {sell_reason}\n"
                    f"price: {current_price:,.0f} KRW\n"
                    f"profit: {profit_rate * 100:.2f}%"
                )

            continue

        state["highest_price"].pop(ticker, None)

        if state["sold_today"].get(ticker):
            print(f"[{currency}] skip buy because it was sold today")
            continue

        if not signal["result"]:
            continue

        krw_balance = get_balance(balances, "KRW")
        buy_amount = min(BUY_AMOUNT_KRW, krw_balance)

        if buy_amount < MIN_ORDER_KRW:
            print(f"[{currency}] skip buy because KRW balance is too low")
            continue

        if buy_coin(ticker, buy_amount):
            send_telegram_msg(
                f"[{currency}] BUY DONE\n"
                f"price: {current_price:,.0f} KRW\n"
                f"target: {market['target_price']:,.0f} KRW\n"
                f"MA: {market['ma5']:,.0f} > {market['ma10']:,.0f} > {market['ma20']:,.0f}\n"
                f"RSI: {market['rsi']:.1f}\n"
                f"volume: {market['today_volume']:.0f} / avg5 {market['avg_volume5']:.0f}"
            )

    if status_lines:
        report = (
            f"Bot status {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + "\n\n".join(status_lines)
        )
        send_telegram_msg(report)

    save_state(state)


if __name__ == "__main__":
    main()
