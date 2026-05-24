import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("strategy_config.json")

DEFAULT_TARGET_COINS = [
    "KRW-BTC",
    "KRW-ETH",
    "KRW-SOL",
    "KRW-XRP",
    "KRW-DOGE",
]

DEFAULT_POSITION_PRIORITY = list(DEFAULT_TARGET_COINS)


@dataclass
class StrategyConfig:
    # symbols
    target_coins: list[str]
    position_priority: list[str]
    interval: str = "minute15"

    # order sizing
    buy_amount_krw: float = 10_000
    min_order_krw: float = 5_000
    fee_rate: float = 0.0005

    # signal params
    rsi_min: float = 48
    rsi_max: float = 72
    volume_multiplier: float = 1.3
    max_chase_rate: float = 0.003
    adx_min: float = 20
    atr_stop_multiplier: float = 1.3
    atr_profit_multiplier: float = 2.2
    trailing_start: float = 0.004
    trailing_drop: float = 0.0025
    sideways_rsi_buy: float = 35
    bbands_period: int = 20
    bbands_std: float = 2

    # portfolio limits
    max_open_positions: int = 2
    max_buy_per_run: int = 1
    max_buy_per_day: int = 4
    min_krw_reserve: float = 20_000

    # backtest
    fill_model: str = "conservative"
    backtest_version: str = "multi-regime-v3"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyConfig":
        kwargs: dict[str, Any] = {}
        field_map = {
            "TARGET_COINS": "target_coins",
            "POSITION_PRIORITY": "position_priority",
            "INTERVAL": "interval",
            "BUY_AMOUNT_KRW": "buy_amount_krw",
            "MIN_ORDER_KRW": "min_order_krw",
            "FEE_RATE": "fee_rate",
            "RSI_MIN": "rsi_min",
            "RSI_MAX": "rsi_max",
            "VOLUME_MULTIPLIER": "volume_multiplier",
            "MAX_CHASE_RATE": "max_chase_rate",
            "ADX_MIN": "adx_min",
            "ATR_STOP_MULTIPLIER": "atr_stop_multiplier",
            "ATR_PROFIT_MULTIPLIER": "atr_profit_multiplier",
            "TRAILING_START": "trailing_start",
            "TRAILING_DROP": "trailing_drop",
            "SIDEWAYS_RSI_BUY": "sideways_rsi_buy",
            "BBANDS_PERIOD": "bbands_period",
            "BBANDS_STD": "bbands_std",
            "MAX_OPEN_POSITIONS": "max_open_positions",
            "MAX_BUY_PER_RUN": "max_buy_per_run",
            "MAX_BUY_PER_DAY": "max_buy_per_day",
            "MIN_KRW_RESERVE": "min_krw_reserve",
            "FILL_MODEL": "fill_model",
            "BACKTEST_VERSION": "backtest_version",
        }
        for json_key, attr in field_map.items():
            if json_key in data:
                kwargs[attr] = data[json_key]

        if "tickers" in data and "target_coins" not in kwargs:
            kwargs["target_coins"] = data["tickers"]

        if "target_coins" not in kwargs:
            kwargs["target_coins"] = list(DEFAULT_TARGET_COINS)
        if "position_priority" not in kwargs:
            kwargs["position_priority"] = list(kwargs["target_coins"])

        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in kwargs.items() if k in allowed})

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "TARGET_COINS": self.target_coins,
            "POSITION_PRIORITY": self.position_priority,
            "INTERVAL": self.interval,
            "BUY_AMOUNT_KRW": self.buy_amount_krw,
            "MIN_ORDER_KRW": self.min_order_krw,
            "FEE_RATE": self.fee_rate,
            "RSI_MIN": self.rsi_min,
            "RSI_MAX": self.rsi_max,
            "VOLUME_MULTIPLIER": self.volume_multiplier,
            "MAX_CHASE_RATE": self.max_chase_rate,
            "ADX_MIN": self.adx_min,
            "ATR_STOP_MULTIPLIER": self.atr_stop_multiplier,
            "ATR_PROFIT_MULTIPLIER": self.atr_profit_multiplier,
            "TRAILING_START": self.trailing_start,
            "TRAILING_DROP": self.trailing_drop,
            "SIDEWAYS_RSI_BUY": self.sideways_rsi_buy,
            "BBANDS_PERIOD": self.bbands_period,
            "BBANDS_STD": self.bbands_std,
            "MAX_OPEN_POSITIONS": self.max_open_positions,
            "MAX_BUY_PER_RUN": self.max_buy_per_run,
            "MAX_BUY_PER_DAY": self.max_buy_per_day,
            "MIN_KRW_RESERVE": self.min_krw_reserve,
            "FILL_MODEL": self.fill_model,
            "BACKTEST_VERSION": self.backtest_version,
            "tickers": self.target_coins,
        }


def load_strategy_config(path: Path | str = DEFAULT_CONFIG_PATH) -> StrategyConfig:
    config_path = Path(path)
    if not config_path.exists():
        print(f"[CONFIG] {config_path} 없음 — 기본값 사용")
        return StrategyConfig(
            target_coins=list(DEFAULT_TARGET_COINS),
            position_priority=list(DEFAULT_POSITION_PRIORITY),
        )

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        cfg = StrategyConfig.from_dict(data)
        print(f"[CONFIG] {config_path} 로드 완료 (v={cfg.backtest_version})")
        return cfg
    except Exception as exc:
        print(f"[CONFIG LOAD ERROR] {exc}")
        return StrategyConfig(
            target_coins=list(DEFAULT_TARGET_COINS),
            position_priority=list(DEFAULT_POSITION_PRIORITY),
        )
