from typing import Any

from strategy.config import StrategyConfig


def should_buy(current_price: float, market: dict[str, Any], cfg: StrategyConfig) -> bool:
    if market["rsi"] >= cfg.rsi_max:
        return False

    if market["mode"] == "TREND":
        breakout = current_price > market["target_price"]
        uptrend = market["ma5"] > market["ma10"] and current_price > market["ma20"]
        volume_ok = market["today_volume"] > market["avg_volume5"] * cfg.volume_multiplier
        chase_ok = current_price < market["target_price"] * (1 + cfg.max_chase_rate)
        return breakout and uptrend and volume_ok and chase_ok

    if market["mode"] == "SIDEWAYS":
        near_lower = current_price <= market["bb_lower"] * 1.01
        rsi_ok = market["rsi"] <= cfg.sideways_rsi_buy
        return near_lower and rsi_ok

    return False


def get_sell_signal(
    current_price: float,
    avg_buy_price: float,
    market: dict[str, Any],
    state: dict[str, Any],
    ticker: str,
    cfg: StrategyConfig,
) -> tuple[bool, str]:
    if avg_buy_price <= 0:
        return False, ""

    atr_stop = market["atr"] * cfg.atr_stop_multiplier
    atr_target = market["atr"] * cfg.atr_profit_multiplier
    highest_map = state.setdefault("highest_price", {})
    highest = max(highest_map.get(ticker, 0), current_price)
    highest_map[ticker] = highest

    trailing_drop = (current_price - highest) / highest if highest > 0 else 0
    profit_rate = (current_price - avg_buy_price) / avg_buy_price

    if current_price >= avg_buy_price + atr_target:
        return True, "ATR TAKE PROFIT"
    if current_price <= avg_buy_price - atr_stop:
        return True, "ATR STOP LOSS"
    if profit_rate >= cfg.trailing_start and trailing_drop <= -cfg.trailing_drop:
        return True, "TRAILING STOP"
    if current_price < market["prev_low"]:
        return True, "BREAK PREVIOUS LOW"

    return False, ""
