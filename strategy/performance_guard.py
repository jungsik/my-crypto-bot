from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from strategy.config import StrategyConfig

KST = ZoneInfo("Asia/Seoul")


class PerformanceGuard:
    """일일 손실 한도·연속 손절 시 매수 중단."""

    def __init__(self, cfg: StrategyConfig, state: dict[str, Any]):
        self.cfg = cfg
        self.state = state
        self._reset_daily_if_needed()

    def _today_kst(self) -> str:
        return datetime.now(KST).strftime("%Y-%m-%d")

    def _reset_daily_if_needed(self) -> None:
        today = self._today_kst()
        if self.state.get("daily_equity_date") != today:
            self.state["daily_equity_date"] = today
            self.state["daily_equity_start"] = 0.0
            self.state["consecutive_losses"] = 0
            self.state["buy_paused_reason"] = ""

    def refresh_daily_start_equity(self, equity: float) -> None:
        today = self._today_kst()
        if self.state.get("daily_equity_date") != today:
            self.state["daily_equity_date"] = today
            self.state["daily_equity_start"] = equity
            self.state["consecutive_losses"] = 0
            self.state["buy_paused_reason"] = ""
            return
        if float(self.state.get("daily_equity_start") or 0) <= 0 and equity > 0:
            self.state["daily_equity_start"] = equity

    def daily_pnl_pct(self, current_equity: float) -> float:
        start = float(self.state.get("daily_equity_start") or 0)
        if start <= 0:
            return 0.0
        return (current_equity - start) / start * 100

    def record_sell(self, profit_pct: float, *, dry_run: bool = False) -> None:
        if dry_run:
            return
        if profit_pct < 0:
            self.state["consecutive_losses"] = int(self.state.get("consecutive_losses", 0)) + 1
        else:
            self.state["consecutive_losses"] = 0
            if str(self.state.get("buy_paused_reason", "")).startswith("CONSECUTIVE"):
                self.state["buy_paused_reason"] = ""

    def can_open_new_buys(self, current_equity: float) -> tuple[bool, str]:
        if not self.cfg.performance_guard_enabled:
            return True, ""

        self.refresh_daily_start_equity(current_equity)
        pnl = self.daily_pnl_pct(current_equity)

        if pnl <= self.cfg.daily_loss_limit_pct:
            reason = f"DAILY_LOSS_LIMIT pnl={pnl:.2f}%"
            self.state["buy_paused_reason"] = reason
            return False, reason

        losses = int(self.state.get("consecutive_losses", 0))
        if losses >= self.cfg.max_consecutive_losses:
            reason = f"CONSECUTIVE_LOSSES count={losses}"
            self.state["buy_paused_reason"] = reason
            return False, reason

        self.state["buy_paused_reason"] = ""
        return True, ""
