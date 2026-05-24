import datetime
import json
import os
from pathlib import Path

import pyupbit
import requests


# =========================================================
# GitHub Actions용 업비트 자동매매 봇
# - 5분마다 1회 실행 후 종료
# - BTC / ETH 기본 설정
# - 변동성 돌파 + MA 추세 + RSI + 거래량 + 추격매수 방지
# =========================================================

ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

BUY_AMOUNT_KRW = 10000
MIN_ORDER_KRW = 5000

DEFAULT_K = 0.5
DEFENSE_K = 0.7

NORMAL_PROFIT_TARGET = 0.01
BULL_PROFIT_TARGET = 0.03
STOP_LOSS = -0.02
HARD_PROFIT_TARGET = 0.015
TRAILING_START = 0.006
TRAILING_DROP = 0.0045

FEE_RATE = 0.0005
STATE_FILE = Path("bot_state.json")
STRATEGY_CONFIG_FILE = Path("strategy_config.json")

RSI_MIN = 50
RSI_MAX = 75
VOLUME_MULTIPLIER = 1.2
MAX_CHASE_RATE = 0.01


upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)


def load_strategy_config():
    global RSI_MIN, RSI_MAX, VOLUME_MULTIPLIER, MAX_CHASE_RATE

    if not STRATEGY_CONFIG_FILE.exists():
        print("[CONFIG] strategy_config.json not found. Use default values.")
        return

    try:
        config = json.loads(STRATEGY_CONFIG_FILE.read_text(encoding="utf-8"))
        RSI_MIN = int(config.get("RSI_MIN", RSI_MIN))
        RSI_MAX = int(config.get("RSI_MAX", RSI_MAX))
        VOLUME_MULTIPLIER = float(
            config.get("VOLUME_MULTIPLIER", VOLUME_MULTIPLIER)
        )
        MAX_CHASE_RATE = float(config.get("MAX_CHASE_RATE", MAX_CHASE_RATE))

        print(
            "[CONFIG] loaded "
            f"RSI={RSI_MIN}~{RSI_MAX}, "
            f"VOLx={VOLUME_MULTIPLIER}, "
            f"CHASE={MAX_CHASE_RATE}"
        )
    except Exception as e:
        print("[CONFIG LOAD ERROR]", e)


def send_telegram_msg(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TELEGRAM SKIP]", message)
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )

        if response.status_code != 200:
            print("[TELEGRAM ERROR]", response.status_code, response.text)

    except Exception as e:
        print("[TELEGRAM EXCEPTION]", e)


def load_state():
    if not STATE_FILE.exists():
        return {"last_reset_date": "", "sold_today": {}, "highest_price": {}}

    try:
