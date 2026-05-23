import time
import datetime
import os
import requests
import pyupbit

# =========================================================
# 업비트 자동매매 봇 (안정화 개선 버전)
# - BTC / ETH 변동성 돌파 전략
# - 중복 주문 방지
# - API 오류 보호
# - 텔레그램 알림
# - 이동평균 필터 추가
# - Rate Limit 최소화
# =========================================================

# =========================
# 환경 변수
# =========================
ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY", "").strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# =========================
# 업비트 객체
# =========================
upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)

# =========================
# 설정
# =========================
TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

BUY_AMOUNT_KRW = 10000          # 코인당 매수 금액
MIN_ORDER_KRW = 5000            # 업비트 최소 주문 금액

DEFAULT_K = 0.5
DEFAULT_PROFIT_TARGET = 0.01    # +1%
DEFAULT_STOP_LOSS = -0.02       # -2%

LOOP_INTERVAL = 3               # 루프 주기 (초)

# =========================
# 상태 저장
# =========================
buy_prices = {}
is_target_achieved = {}
today_profit_targets = {}
today_k_values = {}

last_reset_date = None

for coin in TARGET_COINS:
    buy_prices[coin] = 0
    is_target_achieved[coin] = False
    today_profit_targets[coin] = DEFAULT_PROFIT_TARGET
    today_k_values[coin] = DEFAULT_K

# =========================================================
# 텔레그램
# =========================================================
def send_telegram_msg(message):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[텔레그램 미설정]")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }

        response = requests.post(url, json=payload, timeout=10)

        if response.status_code != 200:
            print(f"[텔레그램 오류] {response.text}")

    except Exception as e:
        print(f"[텔레그램 예외] {e}")

# =========================================================
# 현재가 조회
# =========================================================
def get_current_price(ticker):
    try:
        price = pyupbit.get_current_price(ticker)

        if price is None:
            return 0

        return float(price)

    except Exception as e:
        print(f"[현재가 조회 오류] {ticker} / {e}")
        return 0

# =========================================================
# 시작 시간
# =========================================================
def get_start_time(ticker):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
        return df.index[0]

    except Exception as e:
        print(f"[시작시간 오류] {ticker} / {e}")
        return None

# =========================================================
# 잔고 조회
# =========================================================
def get_all_balances():
    try:
        balances = upbit.get_balances()

        if isinstance(balances, list):
            return balances

        return []

    except Exception as e:
        print(f"[잔고 조회 오류] {e}")
        return []

def get_balance_from_cache(balances, currency):
    try:
        for b in balances:
            if b.get("currency") == currency:
                return float(b.get("balance", 0))

        return 0

    except:
        return 0

def get_avg_buy_price_from_cache(balances, currency):
    try:
        for b in balances:
            if b.get("currency") == currency:
                return float(b.get("avg_buy_price", 0))

        return 0

    except:
        return 0

# =========================================================
# 변동성 돌파 목표가 계산
# =========================================================
def get_target_price(ticker, k):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=2)

        today_open = df.iloc[-1]["open"]

        yesterday_high = df.iloc[0]["high"]
        yesterday_low = df.iloc[0]["low"]

        target_price = today_open + (yesterday_high - yesterday_low) * k

        return (
            float(target_price),
            float(today_open),
            float(yesterday_low)
        )

    except Exception as e:
        print(f"[목표가 계산 오류] {ticker} / {e}")
        return (0, 0, 0)

# =========================================================
# 이동평균 필터
# =========================================================
def get_ma5(ticker):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=5)

        ma5 = df["close"].rolling(5).mean().iloc[-1]

        return float(ma5)

    except Exception as e:
        print(f"[MA5 오류] {ticker} / {e}")
        return 0

# =========================================================
# 시장 상태 분석
# =========================================================
def check_market_condition_and_set_policy(ticker):
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=2)

        yesterday_open = df.iloc[0]["open"]
        yesterday_close = df.iloc[0]["close"]

        yesterday_return_pct = (
            (yesterday_close - yesterday_open)
            / yesterday_open
        ) * 100

        coin_name = ticker.split("-")[-1]

        # 불장
        if yesterday_return_pct >= 8:
            today_profit_targets[ticker] = 0.03
            today_k_values[ticker] = 0.5

            msg = (
                f"🔥 [{coin_name}] 불장 모드\n"
                f"전일 수익률: {yesterday_return_pct:.2f}%\n"
                f"익절 목표: 3%"
            )

        # 약세장
        elif yesterday_return_pct <= -5:
            today_profit_targets[ticker] = 0.01
            today_k_values[ticker] = 0.7

            msg = (
                f"❄️ [{coin_name}] 방어 모드\n"
                f"전일 수익률: {yesterday_return_pct:.2f}%\n"
                f"K값 강화: 0.7"
            )

        # 일반장
        else:
            today_profit_targets[ticker] = 0.01
            today_k_values[ticker] = 0.5

            msg = (
                f"💤 [{coin_name}] 일반 모드\n"
                f"전일 수익률: {yesterday_return_pct:.2f}%"
            )

        print(msg)
        send_telegram_msg(msg)

    except Exception as e:
        print(f"[시장 분석 오류] {ticker} / {e}")

# =========================================================
# 시장가 매수
# =========================================================
def buy_coin(ticker, amount_krw):
    try:
        result = upbit.buy_market_order(
            ticker,
            amount_krw * 0.9995
        )

        if result is not None:
            return True

        return False

    except Exception as e:
        print(f"[매수 오류] {ticker} / {e}")
        return False

# =========================================================
# 시장가 매도
# =========================================================
def sell_coin(ticker, volume):
    try:
        result = upbit.sell_market_order(ticker, volume)

        if result is not None:
            return True

        return False

    except Exception as e:
        print(f"[매도 오류] {ticker} / {e}")
        return False

# =========================================================
# 시작 메시지
# =========================================================
start_msg = (
    "🤖 업비트 자동매매 봇 시작\n"
    "전략: 변동성 돌파 + MA5 필터"
)

print(start_msg)
send_telegram_msg(start_msg)

# =========================================================
# 메인 루프
# =========================================================
while True:

    try:

        now = datetime.datetime.now()

        start_time = get_start_time("KRW-BTC")

        if start_time is None:
            time.sleep(LOOP_INTERVAL)
            continue

        end_time = start_time + datetime.timedelta(days=1)

        # =================================================
        # 하루 1회 초기화
        # =================================================
        today = now.date()

        if last_reset_date != today:

            last_reset_date = today

            print("[일일 초기화 진행]")

            for coin in TARGET_COINS:

                is_target_achieved[coin] = False
                buy_prices[coin] = 0

                check_market_condition_and_set_policy(coin)

            send_telegram_msg("📅 일일 전략 초기화 완료")

        # =================================================
        # 잔고 캐싱
        # =================================================
        balances = get_all_balances()

        # =================================================
        # 거래 시간
        # =================================================
        if start_time < now < end_time - datetime.timedelta(seconds=10):

            for coin in TARGET_COINS:

                currency = coin.split("-")[-1]

                current_price = get_current_price(coin)

                if current_price <= 0:
                    continue

                coin_balance = get_balance_from_cache(
                    balances,
                    currency
                )

                avg_buy_price = get_avg_buy_price_from_cache(
                    balances,
                    currency
                )

                target_price, today_open, prev_low = get_target_price(
                    coin,
                    today_k_values[coin]
                )

                ma5 = get_ma5(coin)

                # =========================================
                # 보유 중
                # =========================================
                if coin_balance > 0.00001:

                    buy_prices[coin] = avg_buy_price

                    profit_rate = (
                        (current_price - avg_buy_price)
                        / avg_buy_price
                    )

                    # 익절
                    if profit_rate >= today_profit_targets[coin]:

                        success = sell_coin(coin, coin_balance)

                        if success:

                            msg = (
                                f"🎉 [{currency}] 익절 완료\n"
                                f"수익률: {profit_rate*100:.2f}%\n"
                                f"매도가: {current_price:,.0f}원"
                            )

                            print(msg)
                            send_telegram_msg(msg)

                            is_target_achieved[coin] = True
                            buy_prices[coin] = 0

                            time.sleep(1)
                            continue

                    # 손절
                    elif profit_rate <= DEFAULT_STOP_LOSS:

                        success = sell_coin(coin, coin_balance)

                        if success:

                            msg = (
                                f"🚨 [{currency}] 손절 실행\n"
                                f"손실률: {profit_rate*100:.2f}%\n"
                                f"매도가: {current_price:,.0f}원"
                            )

                            print(msg)
                            send_telegram_msg(msg)

                            is_target_achieved[coin] = True
                            buy_prices[coin] = 0

                            time.sleep(1)
                            continue

                    # 전일 저점 이탈
                    elif current_price < prev_low:

                        success = sell_coin(coin, coin_balance)

                        if success:

                            msg = (
                                f"⚠️ [{currency}] 전일 저점 붕괴\n"
                                f"저점 기준: {prev_low:,.0f}원\n"
                                f"현재가: {current_price:,.0f}원"
                            )

                            print(msg)
                            send_telegram_msg(msg)

                            is_target_achieved[coin] = True
                            buy_prices[coin] = 0

                            time.sleep(1)
                            continue

                # =========================================
                # 미보유 상태 -> 매수 검사
                # =========================================
                else:

                    if is_target_achieved[coin]:
                        continue

                    # MA5 위 + 돌파 성공
                    if current_price > ma5 and current_price > target_price:

                        krw_balance = get_balance_from_cache(
                            balances,
                            "KRW"
                        )

                        buy_amount = min(
                            BUY_AMOUNT_KRW,
                            krw_balance
                        )

                        if buy_amount >= MIN_ORDER_KRW:

                            success = buy_coin(
                                coin,
                                buy_amount
                            )

                            if success:

                                msg = (
                                    f"🛒 [{currency}] 매수 완료\n"
                                    f"현재가: {current_price:,.0f}원\n"
                                    f"목표가 돌파 성공\n"
                                    f"MA5 상단 유지"
                                )

                                print(msg)
                                send_telegram_msg(msg)

                                time.sleep(2)

        # =================================================
        # 장 종료 전 청산
        # =================================================
        else:

            for coin in TARGET_COINS:

                currency = coin.split("-")[-1]

                coin_balance = get_balance_from_cache(
                    balances,
                    currency
                )

                if coin_balance > 0.00001:

                    success = sell_coin(
                        coin,
                        coin_balance
                    )

                    if success:

                        msg = (
                            f"⏳ [{currency}] 장마감 청산 완료"
                        )

                        print(msg)
                        send_telegram_msg(msg)

                        time.sleep(1)

        # =================================================
        # 루프 대기
        # =================================================
        time.sleep(LOOP_INTERVAL)

    except Exception as e:

        error_msg = f"[메인 루프 오류] {e}"

        print(error_msg)

        try:
            send_telegram_msg(error_msg)
        except:
            pass

        time.sleep(5)
