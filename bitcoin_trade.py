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
