from backtest.engine import BacktestResult


def print_backtest_summary(result: BacktestResult, title: str = "Backtest") -> None:
    print("=" * 80)
    print(title)
    print("=" * 80)
    print(f"Return:     {result.return_pct:.2f}%")
    print(f"Trades:     {result.trade_count}")
    print(f"Win rate:   {result.win_rate:.2f}%")
    print(f"Max DD:     {result.max_drawdown:.2f}%")

    if result.regime_stats:
        print("\nRegime stats:")
        for mode, stats in sorted(result.regime_stats.items()):
            trades = int(stats.get("trades", 0))
            wins = int(stats.get("wins", 0))
            wr = wins / trades * 100 if trades else 0
            print(f"  {mode:10s} entries={trades:4d}  wins={wins:4d}  win_rate={wr:.1f}%")
