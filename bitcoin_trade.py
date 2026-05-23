import time
import datetime
import pyupbit
import os
import requests

# 1. API 키 및 텔레그램 설정 (환경변수 연동)
ACCESS_KEY = os.environ.get('UPBIT_ACCESS_KEY', "본인의_ACCESS_KEY_입력").strip()
SECRET_KEY = os.environ.get('UPBIT_SECRET_KEY', "본인의_SECRET_KEY_입력").strip()
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', "본인의_TELEGRAM_TOKEN_입력").strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "본인의_CHAT_ID_입력").strip()

# 업비트 주문 전용 객체 생성
upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)

TARGET_COINS = ["KRW-BTC", "KRW-ETH"]

buy_prices = {coin: 0 for coin in TARGET_COINS}
is_target_achieved = {coin: False for coin in TARGET_COINS}
today_profit_targets = {coin: 0.01 for coin in TARGET_COINS}
today_k_values = {coin: 0.5 for coin in TARGET_COINS}

def send_telegram_msg(message):
    """💡 주소 중복 파싱 에러를 완벽하게 정화하는 방어용 발송 함수"""
    try:
        # 혹시 토큰에 주소 전체가 들어왔을 경우를 대비한 3중 정화 필터
        clean_token = TELEGRAM_TOKEN.replace("https://telegram.org", "")
        clean_token = clean_token.replace("https://telegram.org", "")
        clean_token = clean_token.replace("/sendMessage", "")
        clean_token = clean_token.strip("/* ") # 슬래시나 별표, 공백 완전 제거
        
        # 완전무결한 단일 주소 조립
        url = f"https://telegram.org{clean_token}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID.strip(), "text": message}
        
        response = requests.post(url, json=payload, timeout=10)
        print(f"텔레그램 발송 시도 결과 코드: {response.status_code}")
    except Exception as e:
        print(f"텔레그램 발송 내부 예외 발생: {e}")

def get_current_price_via_api(ticker):
    """💡 업비트 트래픽 거부 및 데이터 타입 에러를 완전히 지워버리는 현재가 함수"""
    try:
        url = f"https://upbit.com{ticker}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        
        # 데이터가 리스트이고 내부에 딕셔너리가 정상 존재할 때만 안전하게 접근
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            if 'trade_price' in data[0]:
                return float(data[0]['trade_price'])
        
        # 예외 상황 발생 시 안정적인 라이브러리 백업 시세 사용
        return float(pyupbit.get_current_price(ticker))
    except Exception as e:
        # 에러가 나더라도 무조건 시세를 반환하여 프로그램을 지속시킴
        return float(pyupbit.get_current_price(ticker))

def check_market_condition_and_set_policy(ticker):
    """어제 수익률에 따라 오늘 익절 목표와 K값을 능동 변경"""
    global today_profit_targets, today_k_values
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=2)
        yesterday_open = df.iloc[0]['open']
        yesterday_close = df.iloc[0]['close']
        
        yesterday_return_pct = ((yesterday_close - yesterday_open) / yesterday_open) * 100
        coin_name = ticker.split("-")[-1]
        
        if yesterday_return_pct >= 10.0:
            today_profit_targets[ticker] = 0.05
            today_k_values[ticker] = 0.5
            msg = f"🔥 [{coin_name} 불장 모드] 전날 {yesterday_return_pct:.1f}% 폭등!\n🎯 오늘 목표 수익률을 [5%]로 상향합니다. (K: 0.5)"
        elif yesterday_return_pct <= -5.0:
            today_profit_targets[ticker] = 0.01
            today_k_values[ticker] = 0.7
            msg = f"❄️ [{coin_name} 방어 모드] 전날 {yesterday_return_pct:.1f}% 폭락..\n⚠️ 가짜 반등 방지를 위해 매수 진입 K값을 [0.7]로 높입니다. (목표: 1%)"
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
    return df.index

def get_balance(ticker):
    """안전 잔고 조회 함수"""
    try:
        balances = upbit.get_balances()
        if isinstance(balances, list):
            for b in balances:
                if isinstance(b, dict) and b.get('currency') == ticker:
                    return float(b['balance']) if b.get('balance') is not None else 0
        return 0
    except Exception as e:
        print(f"잔고 조회 오류 건너뜀: {e}")
        return 0

def get_avg_buy_price(ticker):
    """실제 보유 중인 코인의 평단가 조회"""
    try:
        balances = upbit.get_balances()
        if isinstance(balances, list):
            for b in balances:
                if isinstance(b, dict) and b.get('currency') == ticker:
                    return float(b['avg_buy_price']) if b.get('avg_buy_price'] is not None else 0
        return 0
    except Exception as e:
        return 0

# 프로그램 기동 시 최초 평가 실행
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

        if start_time <= now < start_time + datetime.timedelta(seconds=5):
            for coin in TARGET_COINS:
                is_target_achieved[coin] = False
                buy_prices[coin] = 0
                check_market_condition_and_set_policy(coin) 
            time.sleep(5) 

        if start_time < now < end_time - datetime.timedelta(seconds=10):
            for coin in TARGET_COINS:
                currency_code = coin.split("-")[-1]
                coin_balance = get_balance(currency_code)
                current_price = get_current_price_via_api(coin)
                
                target_price, today_open, prev_low_line = get_target_and_support(coin, k=today_k_values[coin])
                
                if coin_balance > 0.00001:
                    if buy_prices[coin] == 0:
                        buy_prices[coin] = get_avg_buy_price(currency_code)
                    
                    sell_trigger_price = buy_prices[coin] * (1.0 + today_profit_targets[coin] + 0.001)
                    
                    if current_price >= sell_trigger_price:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🎉 [{currency_code} 익절 완료] 목표 {today_profit_targets[coin]*100}% 수익 실현!\n· 평단가: {buy_prices[coin]:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True 
                        buy_prices[coin] = 0
                    
                    elif current_price <= buy_prices[coin] * 0.979:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🚨 [{currency_code} 고정손절] 무조건 손절 매도 (-2%)\n· 평단가: {buy_prices[coin]:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True
                        buy_prices[coin] = 0
                        
                    elif current_price < today_open:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🚨 [{currency_code} 시가손절] 당일 시가선 붕괴 이탈 매도\n· 시가기준: {today_open:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True
                        buy_prices[coin] = 0
                        
                    elif current_price < prev_low_line:
                        upbit.sell_market_order(coin, coin_balance)
                        msg = f"🚨 [{currency_code} 저점손절] 어제 지지 바닥선 붕괴 매도\n· 저점기준: {prev_low_line:,.0f}원\n· 매도전송: {current_price:,.0f}원"
                        send_telegram_msg(msg)
                        is_target_achieved[coin] = True
                        buy_prices[coin] = 0
                
                elif not is_target_achieved[coin]:
                    if target_price < current_price:
                        krw = get_balance("KRW")
                        buy_amount = 10000 if krw >= 10000 else krw
                        
                        if buy_amount > 5000:
                            upbit.buy_market_order(coin, buy_amount * 0.9995)
                            time.sleep(2) 
                            buy_prices[coin] = get_avg_buy_price(currency_code)
                            msg = f"🛒 [{currency_code} 매수 완료] 변동성 돌파 성공!\n· 진입평단: {buy_prices[coin]:,.0f}원\n· 오늘목표: {today_profit_targets[coin]*100}%"
                            send_telegram_msg(msg)
                    
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
        print(f"시스템 예외 루프 보호 제어 중: {e}")
        time.sleep(1)
