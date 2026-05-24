import numpy as np
import pandas as pd


def calculate_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    value = float(rsi.iloc[-1])
    return 50.0 if np.isnan(value) else value


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    value = float(atr.iloc[-1])
    return 0.0 if np.isnan(value) else value


def calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
    plus_dm = df["high"].diff()
    minus_dm = df["low"].diff() * -1
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    di_sum = plus_di + minus_di
    dx = np.where(di_sum == 0, 0, ((plus_di - minus_di).abs() / di_sum) * 100)

    adx = pd.Series(dx, index=df.index).rolling(period).mean()
    value = float(adx.iloc[-1])
    return 0.0 if np.isnan(value) else value


def calculate_bollinger(close: pd.Series, period: int, std_dev: float) -> dict[str, float]:
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + (std * std_dev)
    lower = ma - (std * std_dev)
    return {
        "upper": float(upper.iloc[-1]),
        "middle": float(ma.iloc[-1]),
        "lower": float(lower.iloc[-1]),
    }
