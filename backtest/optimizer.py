from __future__ import annotations

import datetime
import json
from copy import deepcopy
from itertools import product
from pathlib import Path
from typing import Any

import pyupbit

from backtest.engine import run_portfolio_backtest
from strategy.config import StrategyConfig, load_strategy_config


def load_ohlcv(ticker: str, count: int, interval: str = "minute15"):
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
    if df is None or len(df) < 60:
        raise RuntimeError(f"{ticker}: 캔들 데이터 부족 (count={count})")
    return df.dropna().copy()


def make_param_grid() -> list[dict[str, float]]:
    rsi_mins = [45, 48, 50]
    rsi_maxs = [70, 72, 75]
    volume_multipliers = [1.1, 1.2, 1.3, 1.5]
    configs = []
    for rsi_min, rsi_max, volume_multiplier in product(rsi_mins, rsi_maxs, volume_multipliers):
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


def score_result(result: dict[str, float]) -> float:
    if result["trade_count"] < 3:
        return -9999
    return result["return_pct"] + result["win_rate"] * 0.05 + result["max_drawdown"] * 0.4


def optimize(
    tickers: list[str],
    count: int,
    cash: float,
    top: int,
    base_cfg: StrategyConfig | None = None,
) -> list[dict[str, Any]]:
    base = base_cfg or load_strategy_config()
    data = {ticker: load_ohlcv(ticker, count, base.interval) for ticker in tickers}
    results: list[dict[str, Any]] = []

    for params in make_param_grid():
        cfg = deepcopy(base)
        cfg.rsi_min = params["rsi_min"]
        cfg.rsi_max = params["rsi_max"]
        cfg.volume_multiplier = params["volume_multiplier"]
        cfg.target_coins = tickers
        cfg.position_priority = [t for t in base.position_priority if t in tickers] or list(tickers)

        bt = run_portfolio_backtest(data, cfg, cash, use_limits=True)
        item = {
            "return_pct": bt.return_pct,
            "trade_count": bt.trade_count,
            "win_rate": bt.win_rate,
            "max_drawdown": bt.max_drawdown,
            "score": score_result(
                {
                    "return_pct": bt.return_pct,
                    "trade_count": bt.trade_count,
                    "win_rate": bt.win_rate,
                    "max_drawdown": bt.max_drawdown,
                }
            ),
            "config": params,
            "regime_stats": bt.regime_stats,
        }
        results.append(item)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top]


def print_results(results: list[dict[str, Any]]) -> None:
    print("=" * 80)
    print("Backtest optimizer (bitcoin_trade 동일 전략 · 포트폴리오 한도 ON)")
    print("=" * 80)
    for idx, item in enumerate(results, start=1):
        c = item["config"]
        print(
            f"{idx}. score={item['score']:.2f} return={item['return_pct']:.2f}% "
            f"win={item['win_rate']:.2f}% mdd={item['max_drawdown']:.2f}% "
            f"trades={item['trade_count']} | RSI={c['rsi_min']}~{c['rsi_max']} VOLx={c['volume_multiplier']}"
        )


def write_strategy_config(
    results: list[dict[str, Any]],
    path: str | Path,
    tickers: list[str],
    count: int,
    base_cfg: StrategyConfig | None = None,
) -> None:
    if not results:
        raise RuntimeError("optimizer 결과 없음")

    base = base_cfg or load_strategy_config()
    best = results[0]
    params = best["config"]

    payload = base.to_json_dict()
    payload.update(
        {
            "RSI_MIN": params["rsi_min"],
            "RSI_MAX": params["rsi_max"],
            "VOLUME_MULTIPLIER": params["volume_multiplier"],
            "optimized_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "tickers": tickers,
            "count": count,
            "score": round(best["score"], 4),
            "avg_return_pct": round(best["return_pct"], 4),
            "avg_win_rate": round(best["win_rate"], 4),
            "max_drawdown": round(best["max_drawdown"], 4),
            "trade_count": best["trade_count"],
            "BACKTEST_VERSION": base.backtest_version,
        }
    )

    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n설정 저장: {path}")
