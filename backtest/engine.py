from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from strategy.config import StrategyConfig
from strategy.portfolio_guard import PortfolioGuard
from strategy.regime import build_market_snapshot
from strategy.signals import get_sell_signal, should_buy


@dataclass
class Position:
    qty: float = 0.0
    avg_price: float = 0.0
    entry_mode: str = ""


@dataclass
class BacktestResult:
    return_pct: float
    trade_count: int
    win_rate: float
    max_drawdown: float
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    regime_stats: dict[str, dict[str, float]] = field(default_factory=dict)


def _conservative_buy_price(market: dict[str, Any], cfg: StrategyConfig) -> float | None:
    target = market["target_price"]
    high = market["candle_high"]
    if high < target:
        return None
    return max(target, market["candle_open"])


def _intrabar_sell_price(
    avg_buy: float,
    market: dict[str, Any],
    state: dict[str, Any],
    ticker: str,
    cfg: StrategyConfig,
) -> tuple[float, str]:
    """보수적 체결: 손절·저가 이탈은 low, 익절은 high, 트레일링은 close."""
    low = market["candle_low"]
    high = market["candle_high"]
    close = market["candle_close"]
    prev_low = market["prev_low"]

    atr_stop = market["atr"] * cfg.atr_stop_multiplier
    atr_target = market["atr"] * cfg.atr_profit_multiplier
    stop_price = avg_buy - atr_stop
    take_price = avg_buy + atr_target

    if low <= stop_price:
        return stop_price, "ATR STOP LOSS"
    if low < prev_low:
        return prev_low, "BREAK PREVIOUS LOW"
    if high >= take_price:
        return take_price, "ATR TAKE PROFIT"

    highest_map = state.setdefault("highest_price", {})
    highest = max(highest_map.get(ticker, 0), close)
    highest_map[ticker] = highest
    trailing_drop = (close - highest) / highest if highest > 0 else 0
    profit_rate = (close - avg_buy) / avg_buy
    if profit_rate >= cfg.trailing_start and trailing_drop <= -cfg.trailing_drop:
        return close, "TRAILING STOP"

    return 0.0, ""


def _close_based_sell(
    avg_buy: float,
    price: float,
    market: dict[str, Any],
    state: dict[str, Any],
    ticker: str,
    cfg: StrategyConfig,
) -> tuple[bool, str, float]:
    sell, reason = get_sell_signal(price, avg_buy, market, state, ticker, cfg)
    return sell, reason, price if sell else 0.0


def run_portfolio_backtest(
    data_by_ticker: dict[str, pd.DataFrame],
    cfg: StrategyConfig,
    initial_cash: float,
    *,
    use_limits: bool = True,
) -> BacktestResult:
    if not data_by_ticker:
        raise ValueError("data_by_ticker is empty")

    min_len = min(len(df) for df in data_by_ticker.values())
    cash = float(initial_cash)
    positions: dict[str, Position] = {t: Position() for t in data_by_ticker}
    state: dict[str, Any] = {"highest_price": {}, "daily_buy_count": 0, "daily_buy_date": ""}
    guard = PortfolioGuard(cfg, state)
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    regime_stats: dict[str, dict[str, float]] = {}

    tickers = [t for t in cfg.position_priority if t in data_by_ticker]
    tickers += [t for t in data_by_ticker if t not in tickers]

    for idx in range(30, min_len):
        state["daily_buy_count"] = 0
        state["daily_buy_date"] = str(data_by_ticker[tickers[0]].index[idx].date())

        # 1) 매도
        for ticker in tickers:
            pos = positions[ticker]
            if pos.qty <= 0:
                continue

            df = data_by_ticker[ticker]
            market = build_market_snapshot(df, cfg, idx)
            if not market:
                continue

            if cfg.fill_model == "conservative":
                exit_price, reason = _intrabar_sell_price(
                    pos.avg_price, market, state, ticker, cfg
                )
                should_exit = exit_price > 0
            else:
                price = market["candle_close"]
                should_exit, reason, exit_price = _close_based_sell(
                    pos.avg_price, price, market, state, ticker, cfg
                )

            if should_exit:
                sell_krw = pos.qty * exit_price * (1 - cfg.fee_rate)
                profit_pct = (exit_price - pos.avg_price) / pos.avg_price * 100
                cash += sell_krw
                mode = pos.entry_mode or "UNKNOWN"
                regime_stats.setdefault(mode, {"trades": 0, "wins": 0})
                regime_stats[mode]["trades"] += 1
                if profit_pct > 0:
                    regime_stats[mode]["wins"] += 1
                trades.append(
                    {
                        "ticker": ticker,
                        "side": "SELL",
                        "reason": reason,
                        "profit_pct": profit_pct,
                        "idx": idx,
                        "entry_mode": mode,
                    }
                )
                positions[ticker] = Position()
                state["highest_price"].pop(ticker, None)

        holdings = {t: positions[t].qty > 0 for t in tickers}
        open_count = guard.open_position_count(holdings)
        buys_this_run = 0
        candidates: list[dict[str, Any]] = []

        # 2) 매수 후보
        for ticker in tickers:
            if holdings[ticker]:
                continue

            df = data_by_ticker[ticker]
            market = build_market_snapshot(df, cfg, idx)
            if not market:
                continue

            if cfg.fill_model == "conservative":
                entry_price = _conservative_buy_price(market, cfg)
                if entry_price is None:
                    continue
                signal_price = market["candle_close"]
            else:
                signal_price = market["candle_close"]
                entry_price = signal_price

            if not should_buy(signal_price, market, cfg):
                continue

            candidates.append(
                {
                    "ticker": ticker,
                    "market": market,
                    "entry_price": entry_price,
                    "mode": market["mode"],
                }
            )

        ordered = guard.sort_buy_candidates(candidates)

        for item in ordered:
            ticker = item["ticker"]
            buy_krw = min(cfg.buy_amount_krw, cash)
            if use_limits:
                ok, _ = guard.can_buy(
                    open_positions=open_count,
                    buys_this_run=buys_this_run,
                    available_krw=cash,
                    buy_amount=buy_krw,
                )
                if not ok:
                    continue
            elif buy_krw < cfg.min_order_krw:
                continue

            entry = item["entry_price"]
            qty = (buy_krw * (1 - cfg.fee_rate)) / entry
            cash -= buy_krw
            mode = item["mode"]
            positions[ticker] = Position(qty=qty, avg_price=entry, entry_mode=mode)
            holdings[ticker] = True
            open_count += 1
            buys_this_run += 1
            if use_limits:
                guard.record_buy()

            trades.append(
                {
                    "ticker": ticker,
                    "side": "BUY",
                    "reason": mode,
                    "profit_pct": 0.0,
                    "idx": idx,
                    "entry_mode": mode,
                }
            )

        equity = cash
        for ticker in tickers:
            pos = positions[ticker]
            if pos.qty > 0:
                close = float(data_by_ticker[ticker].iloc[idx]["close"])
                equity += pos.qty * close
        equity_curve.append(equity)

    # 승률·레짐 통계
    sell_trades = [t for t in trades if t["side"] == "SELL"]
    wins = [t for t in sell_trades if t["profit_pct"] > 0]
    win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0.0

    final_equity = equity_curve[-1] if equity_curve else cash
    total_return = (final_equity - initial_cash) / initial_cash * 100

    peak = initial_cash
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak * 100
        max_drawdown = min(max_drawdown, drawdown)

    return BacktestResult(
        return_pct=total_return,
        trade_count=len(sell_trades),
        win_rate=win_rate,
        max_drawdown=max_drawdown,
        trades=trades,
        equity_curve=equity_curve,
        regime_stats=regime_stats,
    )

