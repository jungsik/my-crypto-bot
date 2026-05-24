from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from strategy.config import StrategyConfig

KST = ZoneInfo("Asia/Seoul")


class PortfolioGuard:
    def __init__(self, cfg: StrategyConfig, state: dict[str, Any]):
        self.cfg = cfg
        self.state = state
        self._reset_daily_if_needed()

    def _today_kst(self) -> str:
        return datetime.now(KST).strftime("%Y-%m-%d")

    def _reset_daily_if_needed(self) -> None:
        today = self._today_kst()
        if self.state.get("daily_buy_date") != today:
            self.state["daily_buy_date"] = today
            self.state["daily_buy_count"] = 0

    @property
    def daily_buy_count(self) -> int:
        return int(self.state.get("daily_buy_count", 0))

    def record_buy(self) -> None:
        self._reset_daily_if_needed()
        self.state["daily_buy_count"] = self.daily_buy_count + 1

    def open_position_count(self, holdings: dict[str, bool]) -> int:
        return sum(1 for held in holdings.values() if held)

    def can_buy(
        self,
        *,
        open_positions: int,
        buys_this_run: int,
        available_krw: float,
        buy_amount: float,
    ) -> tuple[bool, str]:
        if open_positions >= self.cfg.max_open_positions:
            return False, "MAX_OPEN_POSITIONS"
        if buys_this_run >= self.cfg.max_buy_per_run:
            return False, "MAX_BUY_PER_RUN"
        if self.daily_buy_count >= self.cfg.max_buy_per_day:
            return False, "MAX_BUY_PER_DAY"
        if available_krw - buy_amount < self.cfg.min_krw_reserve:
            return False, "MIN_KRW_RESERVE"
        if buy_amount < self.cfg.min_order_krw:
            return False, "MIN_ORDER_KRW"
        return True, ""

    def sort_buy_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        priority = {t: i for i, t in enumerate(self.cfg.position_priority)}

        def sort_key(item: dict[str, Any]) -> tuple:
            ticker = item["ticker"]
            market = item["market"]
            return (
                priority.get(ticker, 999),
                -market.get("adx", 0),
                -market.get("today_volume", 0) / max(market.get("avg_volume5", 1), 1),
            )

        return sorted(candidates, key=sort_key)
