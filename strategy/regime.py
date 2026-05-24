from typing import Any

import pandas as pd

from strategy.config import StrategyConfig
from strategy.indicators import calculate_adx, calculate_atr, calculate_bollinger, calculate_rsi


def build_market_snapshot(
    df: pd.DataFrame,
    cfg: StrategyConfig,
    idx: int | None = None,
) -> dict[str, Any] | None:
    """라이브/백테스트 공통 시장 스냅샷. idx=None이면 마지막 봉."""
    if df is None or len(df) < 30:
        return None

    if idx is None:
        idx = len(df) - 1
    if idx < 29:
        return None

    window = df.iloc[: idx + 1]
    current = window.iloc[-1]
    prev = window.iloc[-2]
    close = window["close"]

    ma5 = float(close.iloc[-6:-1].mean())
    ma10 = float(close.iloc[-11:-1].mean())
    ma20 = float(close.iloc[-21:-1].mean())

    rsi = calculate_rsi(close.iloc[:-1])
    adx = calculate_adx(window)
    atr = calculate_atr(window)
    bb = calculate_bollinger(close, cfg.bbands_period, cfg.bbands_std)

    avg_volume5 = float(window["volume"].iloc[-6:-1].mean())
    recent_return = ((prev["close"] - prev["open"]) / prev["open"]) * 100

    if adx >= cfg.adx_min and ma5 > ma10 and recent_return >= -0.3:
        mode = "TREND"
    elif adx < cfg.adx_min:
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
        "candle_high": float(current["high"]),
        "candle_low": float(current["low"]),
        "candle_open": float(current["open"]),
        "candle_close": float(current["close"]),
    }
