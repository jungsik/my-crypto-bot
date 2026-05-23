import argparse
import datetime
import json
from itertools import product
from pathlib import Path

import pyupbit


TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000
FEE_RATE = 0.0005

DEFAULT_K = 0.5
DEFENSE_K = 0.7
NORMAL_PROFIT_TARGET = 0.01
BULL_PROFIT_TARGET = 0.03
STOP_LOSS = -0.02


def calculate_rsi(close_series, period=14):
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_policy(yesterday):
    yesterday_return = (
        (yesterday["close"] - yesterday["open"]) / yesterday["open"]
    ) * 100

    if yesterday_return >= 8:
        return DEFAULT_K, BULL_PROFIT_TARGET, "BULL"

    if yesterday_return <= -5:
        return DEFENSE_K, NORMAL_PROFIT_TARGET, "DEFENSE"

    return DEFAULT_K, NORMAL_PROFIT_TARGET, "NORMAL"


def load_data(ticker, count):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=count)

    if df is None or len(df) < 60:
        raise RuntimeError(f"{ticker}: not enough candle data")

    df = df.dropna().copy()
    df["rsi14"] = calculate_rsi(df["close"], 14)
    return df


def run_backtest(df, config, initial_cash):
    cash = float(initial_cash)
    position = 0.0
    buy_price = 0.0
    trades = []
    equity_curve = []

    for idx in range(21, len(df)):
        today = df.iloc[idx]
        yesterday = df.iloc[idx - 1]

        ma5 = float(df["close"].iloc[idx - 5:idx].mean())
        ma10 = float(df["close"].iloc[idx - 10:idx].mean())
        ma20 = float(df["close"].iloc[idx - 20:idx].mean())
        avg_volume5 = float(df["volume"].iloc[idx - 5:idx].mean())
        rsi = float(df["rsi14"].iloc[idx - 1])

        k_value, profit_target, mode = get_policy(yesterday)
        target_price = today["open"] + (yesterday["high"] - yesterday["low"]) * k_value

        if position <= 0:
            breakout = today["high"] > target_price
            uptrend = ma5 > ma10 > ma20
            rsi_ok = config["rsi_min"] <= rsi <= config["rsi_max"]
            volume_ok = today["volume"] > avg_volume5 * config["volume_multiplier"]

            if breakout and uptrend and rsi_ok and volume_ok:
                buy_krw = min(BUY_AMOUNT_KRW, cash)

                if buy_krw >= MIN_ORDER_KRW:
                    entry_price = target_price
                    position = (buy_krw * (1 - FEE_RATE)) / entry_price
                    buy_price = entry_price
                    cash -= buy_krw

        if position > 0:
            take_profit_price = buy_price * (1 + profit_target)
            stop_loss_price = buy_price * (1 + STOP_LOSS)
            exit_price = 0
            reason = ""

            if today["low"] <= stop_loss_price:
                exit_price = stop_loss_price
                reason = "STOP"
            elif today["low"] < yesterday["low"]:
                exit_price = yesterday["low"]
                reason = "PREV_LOW"
            elif today["high"] >= take_profit_price:
                exit_price = take_profit_price
                reason = "PROFIT"
            elif idx == len(df) - 1:
                exit_price = today["close"]
                reason = "LAST"

            if exit_price > 0:
                sell_krw = position * exit_price * (1 - FEE_RATE)
                profit_pct = (exit_price - buy_price) / buy_price * 100
                cash += sell_krw
                trades.append(
                    {
                        "mode": mode,
                        "reason": reason,
                        "profit_pct": profit_pct,
                    }
                )
                position = 0.0
                buy_price = 0.0

        equity_curve.append(cash + position * today["close"])

    final_equity = equity_curve[-1] if equity_curve else cash
    total_return = (final_equity - initial_cash) / initial_cash * 100
    wins = [trade for trade in trades if trade["profit_pct"] > 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    peak = initial_cash
    max_drawdown = 0

    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak * 100
        max_drawdown = min(max_drawdown, drawdown)

    return {
        "return_pct": total_return,
        "trade_count": len(trades),
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
    }


def make_configs():
    rsi_mins = [45, 50, 55]
    rsi_maxs = [70, 75, 80]
    volume_multipliers = [1.0, 1.1, 1.2, 1.3, 1.5]

    configs = []

    for rsi_min, rsi_max, volume_multiplier in product(
        rsi_mins,
        rsi_maxs,
        volume_multipliers,
    ):
        if rsi_min >= rsi_max:
            continue

        configs.append(
            {
                "rsi_min": rsi_min,
                "rsi_max": rsi_max,
                "volume_multiplier": volume_multiplier,
            }
        )

    return configs


def score_result(result):
    if result["trade_count"] < 3:
        return -9999

    return (
        result["return_pct"]
        + result["win_rate"] * 0.05
        + result["max_drawdown"] * 0.4
    )


def optimize(tickers, count, cash, top):
    data_by_ticker = {ticker: load_data(ticker, count) for ticker in tickers}
    results = []

    for config in make_configs():
        combined = {
            "return_pct": 0,
            "trade_count": 0,
            "win_rate_sum": 0,
            "max_drawdown": 0,
        }

        for ticker, df in data_by_ticker.items():
            result = run_backtest(df, config, cash)
            combined["return_pct"] += result["return_pct"]
            combined["trade_count"] += result["trade_count"]
            combined["win_rate_sum"] += result["win_rate"]
            combined["max_drawdown"] = min(
                combined["max_drawdown"],
                result["max_drawdown"],
            )

        combined["avg_return_pct"] = combined["return_pct"] / len(tickers)
        combined["avg_win_rate"] = combined["win_rate_sum"] / len(tickers)
        combined["score"] = score_result(
            {
                "return_pct": combined["avg_return_pct"],
                "trade_count": combined["trade_count"],
                "win_rate": combined["avg_win_rate"],
                "max_drawdown": combined["max_drawdown"],
            }
        )
        combined["config"] = config
        results.append(combined)

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top]


def print_results(results):
    print("=" * 80)
    print("Backtest optimizer result")
    print("=" * 80)

    for idx, item in enumerate(results, start=1):
        config = item["config"]
        print(
            f"{idx}. score={item['score']:.2f} "
            f"return={item['avg_return_pct']:.2f}% "
            f"win={item['avg_win_rate']:.2f}% "
            f"mdd={item['max_drawdown']:.2f}% "
            f"trades={item['trade_count']} | "
            f"RSI={config['rsi_min']}~{config['rsi_max']} "
            f"VOLx={config['volume_multiplier']}"
        )

    if results:
        best = results[0]["config"]
        print("\nRecommended bitcoin_trade.py values:")
        print(f"RSI_MIN = {best['rsi_min']}")
        print(f"RSI_MAX = {best['rsi_max']}")
        print(f"VOLUME_MULTIPLIER = {best['volume_multiplier']}")


def write_strategy_config(results, path, tickers, count):
    if not results:
        raise RuntimeError("No optimizer results to write.")

    best = results[0]["config"]
    payload = {
        "RSI_MIN": best["rsi_min"],
        "RSI_MAX": best["rsi_max"],
        "VOLUME_MULTIPLIER": best["volume_multiplier"],
        "MAX_CHASE_RATE": 0.01,
        "optimized_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "tickers": tickers,
        "count": count,
        "score": round(results[0]["score"], 4),
        "avg_return_pct": round(results[0]["avg_return_pct"], 4),
        "avg_win_rate": round(results[0]["avg_win_rate"], 4),
        "max_drawdown": round(results[0]["max_drawdown"], 4),
        "trade_count": results[0]["trade_count"],
    }

    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote strategy config: {path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Optimize RSI/volume buy filters")
    parser.add_argument("--tickers", nargs="+", default=TARGET_COINS)
    parser.add_argument("--count", type=int, default=365)
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--write-config", default="")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    top_results = optimize(args.tickers, args.count, args.cash, args.top)
    print_results(top_results)

    if args.write_config:
        write_strategy_config(
            top_results,
            args.write_config,
            args.tickers,
            args.count,
        )
