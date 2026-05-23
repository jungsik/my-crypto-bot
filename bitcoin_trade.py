import time
import datetime
import pyupbit
import os
import requests

# 1. API 키 및 텔레그램 설정 (환경변수 연동)
ACCESS_KEY = os.environ.get('UPBIT_ACCESS_KEY', "0wzXAqFYlXqjQZNDh2eBzNzyQDG34N56dWcb4xWM")
SECRET_KEY = os.environ.get('UPBIT_SECRET_KEY', "PVYpPG7mpInfv3M7neWzvpRb7yovAAFdPDiczF9O")
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', "8440478958:AAE3yyEJba12EymtGY0W-pN2QzjjqGDto6U")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "6766226947")

# 업비트 주문 전용 객체 생성 (자산조회, 주문 권한만 사용)
upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)

# 분산 매매 대상 코인 리스트
TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

# 종목별 상태 관리를 위한 딕셔너리 초기화
buy_prices = {coin: 0 for coin in TARGET_COINS}
is_target_achieved = {coin: False for coin in TARGET_COINS}
today_profit_targets = {coin: 0.01 for coin in TARGET_COINS}
today_k_values = {coin: 0.5 for coin in TARGET_COINS}

def send_telegram_msg(message):
    """텔레그램 메시지 전송 함수"""
    try:
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        requests.post(url, json=payload)
    except Exception as e:
        print(f"텔레그램 발송 실패: {e}")

def get_current_price_via_api(ticker):
    """
    💡 [사용자 제안 반영] requests 기반의 순수 HTTP 시세 조회 함수
    업비트 로그인 권한이나 세션 끊김 현상 없이 가장 빠르고 안전하게 현재가를 가져옵니다.
    """
    try:
        url = f"https://api.upbit.com/v1/ticker?markets={ticker}"
        headers = {"Accept": "application/json"}
        response = requests.get(url, headers=headers)
        # 응답 배열에서 첫 번째 항목의 'trade_price'(현재 체결가)를 추출하여 반환 [1]
        return float(response.json()[0]['trade_price'])
    except Exception as e:
        print(f"{ticker} requests 현재가 조회 실패, 라이브러리로 대체: {e}")
        return pyupbit.get_current_price(ticker)

def check_market_condition_and_set_policy(ticker):
    """어제 수익률에 따라 오늘 익절 목표와 K값을 능동 변경"""
    global today_profit_targets, today_k_values
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=2)
        yesterday_open = df.iloc[0]['open']
        yesterday_close = df.iloc[0]['close']
        
        yesterday_return_pct = ((yesterday_close - yesterday_open) / yesterday_open) * 100
        coin_name = ticker.split("-")[-1]
        
        # 🔥 Case 1: 전날 +10% 이상 대폭등 (불장 모드)
        if yesterday_return_pct >= 10.0:
            today_profit_targets[ticker] = 0.05
            today_k_values[ticker] = 0.5
            msg = f"🔥 [{coin_name} 불장 모드] 전날 {yesterday_return_pct:.1f}% 폭등!\n🎯 오늘 목표 수익률을 [5%]로 상향합니다. (K: 0.5)"
        
        # 🛡️ Case 2: 전날 -5% 이하 대폭락 (방어 모드)
        elif yesterday_return_pct <= -5.0:
            today_profit_targets[ticker] = 0.01
            today_k_values[ticker] = 0.7
            msg = f"❄️ [{coin_name} 방어 모드] 전날 {yesterday_return_pct:.1f}% 폭락..\n⚠️ 가짜 반등 방지를 위해 매수 진입 K값을 [0.7]로 높입니다. (목표: 1%)"
            
        # ⚖️ Case 3: 평시 상태 (안정 모드)
        else:
            today_profit_targets[ticker] = 0.01
            today_k_values[ticker] = 0.5
            msg = f"💤 [{coin_name} 안정 모드] 전날 {yesterday_return_pct:.1f}% 평범.\n🎯 기본 전략 가동 (목표: 1% / K: 0.5)"
            
        print(msg)
        send_telegram_msg(msg)
        
    except Exception as e:
        today_profit_targets[ticker] = 0.01
        today_k_values[ticker] = 0.5
        print(f"{ticker} 시장 상태 분석 오류: {e}")

def get_target_and_support(ticker, k):
    """목표가 및 전저점 지지선 산출"""
    df = pyupbit.get_ohlcv(ticker, interval="day", count=2)
    today_open = df.iloc[-1]['open']
    prev_high = df.iloc[0]['high']
    prev_low = df.iloc[0]['low']
    
    target_price = today_open + (prev_high - prev_low) * k
    prev_low_line = prev_low
    return target_price, today_open, prev_low_line

def get_start_time(ticker):
    """시작 시간 조회"""
    df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
    return df.index[0]

def get_balance(ticker):
    """잔고 조회"""
    balances = upbit.get_balances()
    for b in balances:
        if b['currency'] == ticker:
            return float(b['balance']) if b['balance'] is not None else 0
    return 0

def get_avg_buy_price(ticker):
    """실제 보유 중인 코인의 평단가 조회"""
    balances = upbit.get_balances()
    for b in balances:
        if b['currency'] == ticker:
            return float(b['avg_buy_price']) if b['avg_buy_price'] is not None else 0
    return 0

# 프로그램 기동 시 모든 대상 코인의 최초 시장 평가 실행
for coin in TARGET_COINS:
    check_market_condition_and_set_policy(coin)

start_msg = "🤖 [BTC / ETH 2종 분산 가변 전략 시스템] 정상 가동 시작"
print(start_msg)
send_telegram_msg(start_msg)

while True:
    try:
        now = datetime.datetime.now()
        start_time = get_start_time("KRW-BTC") 
        end_time = start_time + datetime.timedelta(days=1) 

        # 🕒 매일 아침 9시 정각 상태 리셋 및 당일 맞춤형 모드 갱신
        if start_time <= now < start_time + datetime.timedelta(seconds=5):
            for coin in TARGET_COINS:
                is_target_achieved[coin] = False
                buy_prices[coin] = 0
                check_market_condition_and_set_policy(coin) 
            time.sleep(5) 

        # 장중 매매 구간 (아침 9시 00분 05초 ~ 다음날 아침 8시 59분 50초)
        if start_time < now < end_time - datetime.timedelta(seconds=10):
            
            for coin in TARGET_COINS:
                currency_code = coin.split("-")[-1] # BTC 또는 ETH
                coin_balance = get_balance(currency_code)
                
                # 💡 새로 추가된 requests 기반 현재가 실시간 동기화
                current_price = get_current_price_via_api(coin)
                
                target_price, today_open, prev_low_line = get_target_and_support(coin, k=today_k_values[coin])
                
                # [상태 1] 해당 코인을 보유 중인 경우 -> 실시간 익절/3중 손절 감시
                if coin_balance > 0.00001:
                    if buy_prices[coin] == 0:
                        buy_prices[coin] = get_avg_buy_price(currency_code)
                    
                    sell_trigger_price = buy_prices[coin] * (1.0 + today_profit_targets[coin] + 0.001)
                    
                    # 📈 가변 익절 달성
                    if current_price >= sell_trigger_price:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🎉 [{currency_code} 익절 완료] 목표 {today_profit_targets[coin]*100}% 수익 실현!\n· 평단가: {buy_prices[coin]:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True 
                        buy_prices[coin] = 0
                    
                    # 📉 [손절 1] 고정 비율 손절 (-2%)
                    elif current_price <= buy_prices[coin] * 0.979:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🚨 [{currency_code} 고정손절] 무조건 손절 매도 (-2%)\n· 평단가: {buy_prices[coin]:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True
                        buy_prices[coin] = 0
                        
                    # 📉 [손절 2] 당일 시가 이탈 손절
                    elif current_price < today_open:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🚨 [{currency_code} 시가손절] 당일 시가선 붕괴 이탈 매도\n· 시가기준: {today_open:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True
                        buy_prices[coin] = 0
                        
                    # 📉 [손절 3] 전저점 이탈 손절
                    elif current_price < prev_low_line:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🚨 [{currency_code} 저점손절] 어제 지지 바닥선 붕괴 매도\n· 저점기준: {prev_low_line:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True
                        buy_prices[coin] = 0
                
                # [상태 2] 코인이 없고, 오늘 매매 성공 기록이 없다면 -> 매수 감시
                elif not is_target_achieved[coin]:
                    if target_price < current_price:
                        krw = get_balance("KRW")
                        
                        # 균등 분할 투자 (2만원 자본금 기준 종목당 1만원 타깃 설정)
                        buy_amount = 10000 if krw >= 10000 else krw
                        
                        if buy_amount > 5000:
                            upbit.buy_market_order(coin, buy_amount * 0.9995)
                            time.sleep(2) 
                            buy_prices[coin] = get_avg_buy_price(currency_code)
                            msg = f"🛒 [{currency_code} 매수 완료] 변동성 돌파 성공!\n· 진입평단: {buy_prices[coin]:,.0f}원\n· 오늘목표: {today_profit_targets[coin]*100}%"
                            send_telegram_msg(msg)
                    
        # 당일 마감 청산 타임 (다음 날 아침 8시 59분 50초)
        else:
            for coin in TARGET_COINS:
                currency_code = coin.split("-")[-1]
                coin_balance = get_balance(currency_code)
                if coin_balance > 0.00001:
                    upbit.sell_market_order(coin, coin_balance)
                    msg = f"⏳ [{currency_code} 장마감 청산] 당일 리스크 방지 강제 전량 매도"
                    send_telegram_msg(msg)
                
        time.sleep(1) 
        
    except Exception as e:
        print(f"시스템 오류 발생 제어 중: {e}")
        time.sleep(1)
