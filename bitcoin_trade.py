import argparse
import datetime
import os
import time

try:
    import pyupbit
except ImportError:
    pyupbit = None

try:
    import requests
except ImportError:
    requests = None


# =========================================================
# 업비트 자동매매 봇 + 백테스트
# - BTC / ETH 변동성 돌파 전략
# - MA5 필터
# - 일봉 기반 백테스트
# - 중복 주문 방지 / 주문 결과 검증
# - API 호출 캐싱으로 Rate Limit 완화
# =========================================================

# =========================
# 환경 변수
# =========================
ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# =========================
# 설정
# =========================
TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000

DEFAULT_K = 0.5
DEFAULT_PROFIT_TARGET = 0.01
DEFAULT_STOP_LOSS = -0.02

LOOP_INTERVAL = 3
ORDER_COOLDOWN_SECONDS = 20
FEE_RATE = 0.0005


class StrategyState:
    def __init__(self, tickers):
        self.buy_prices = {ticker: 0 for ticker in tickers}
        self.is_target_achieved = {ticker: False for ticker in tickers}
        self.today_profit_targets = {
            ticker: DEFAULT_PROFIT_TARGET for ticker in tickers
        }
        self.today_k_values = {ticker: DEFAULT_K for ticker in tickers}
        self.last_order_at = {ticker: None for ticker in tickers}
        self.last_reset_date = None


state = StrategyState(TARGET_COINS)


# =========================================================
# 공통 유틸
# =========================================================
def send_telegram_msg(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[텔레그램 미설정]")
            return

        if requests is None:
            print("[텔레그램 스킵] requests 패키지가 필요합니다.")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}

        response = requests.post(url, json=payload, timeout=10)

        if response.status_code != 200:
            print(f"[텔레그램 오류] {response.text}")

    except Exception as e:
        print(f"[텔레그램 예외] {e}")


def coin_currency(ticker):
    return ticker.split("-")[-1]


def can_order(ticker, now):
    last_order_at = state.last_order_at.get(ticker)

    if last_order_at is None:
        return True
