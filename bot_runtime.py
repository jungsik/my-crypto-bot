"""bitcoin_trade / position_watcher 공통 실행 환경."""

import json
import os
from pathlib import Path

import pyupbit
import requests

from strategy.config import StrategyConfig

ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0").strip().lower() in ("1", "true", "yes")

STATE_FILE = Path("bot_state.json")

_upbit: pyupbit.Upbit | None = None


def get_upbit() -> pyupbit.Upbit:
    global _upbit
    if _upbit is None:
        if not ACCESS_KEY or not SECRET_KEY:
            raise RuntimeError("UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 환경변수 확인 필요")
        _upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)
    return _upbit


def send_telegram(message: str) -> None:
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TELEGRAM DISABLED]\n", message)
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as exc:
        print("[TELEGRAM ERROR]", exc)


def default_state() -> dict:
    return {
        "highest_price": {},
        "daily_buy_count": 0,
        "daily_buy_date": "",
        "daily_equity_start": 0.0,
        "daily_equity_date": "",
        "consecutive_losses": 0,
        "buy_paused_reason": "",
    }


def load_state() -> dict:
    if not STATE_FILE.exists():
        return default_state()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        base = default_state()
        base.update(data)
        return base
    except Exception:
        return default_state()


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_balance(currency: str) -> float:
    try:
        for item in get_upbit().get_balances():
            if item["currency"] == currency:
                return float(item["balance"] or 0)
        return 0.0
    except Exception:
        return 0.0


def get_avg_buy_price(currency: str) -> float:
    try:
        for item in get_upbit().get_balances():
            if item["currency"] == currency:
                return float(item["avg_buy_price"] or 0)
        return 0.0
    except Exception:
        return 0.0


def buy_coin(ticker: str, amount: float, cfg: StrategyConfig) -> bool:
    if DRY_RUN:
        print(f"[DRY_RUN BUY] {ticker} {amount:,.0f} KRW")
        return True
    try:
        result = get_upbit().buy_market_order(ticker, amount * (1 - cfg.fee_rate))
        return bool(result and result.get("uuid"))
    except Exception as exc:
        print("[BUY ERROR]", exc)
        return False


def sell_coin(ticker: str, volume: float) -> bool:
    if DRY_RUN:
        print(f"[DRY_RUN SELL] {ticker} vol={volume}")
        return True
    try:
        result = get_upbit().sell_market_order(ticker, volume)
        return bool(result and result.get("uuid"))
    except Exception as exc:
        print("[SELL ERROR]", exc)
        return False


def collect_holdings(cfg: StrategyConfig) -> dict[str, bool]:
    holdings = {}
    for ticker in cfg.target_coins:
        currency = ticker.split("-")[-1]
        holdings[ticker] = get_balance(currency) > 0.00001
    return holdings


def list_held_tickers(cfg: StrategyConfig) -> list[str]:
    return [t for t, held in collect_holdings(cfg).items() if held]


def estimate_equity_krw(cfg: StrategyConfig) -> float:
    total = 0.0
    try:
        for item in get_upbit().get_balances():
            currency = item["currency"]
            balance = float(item["balance"] or 0)
            if currency == "KRW":
                total += balance
                continue
            if balance <= 0.00001:
                continue
            ticker = f"KRW-{currency}"
            if ticker not in cfg.target_coins:
                continue
            price = pyupbit.get_current_price(ticker)
            if price:
                total += balance * float(price)
    except Exception as exc:
        print("[EQUITY ERROR]", exc)
    return total
