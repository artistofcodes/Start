import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import pytz
import requests
import threading


print("Script execution started...")


# ========== User-Configurable Variables ==========
SYMBOLS = ["XAUUSDm", "BTCUSDm", "ETHUSDm"]  # List of symbols to monitor
TIMEFRAME1 = mt5.TIMEFRAME_H1  # First timeframe user-defined
TIMEFRAME2 = mt5.TIMEFRAME_M30  # Second timeframe user-defined

SHORT_EMA_PERIOD = 21
LONG_EMA_PERIOD = 50

RISK_PERCENT = 1.0
MIN_LOTS = 0.01

BROKER_TZ = "GMT"

TELEGRAM_BOT_TOKEN = "8036989920:AAFkw0NeagSdPab1edlD2UTLKcUahSm8guI"
TELEGRAM_CHAT_ID = "-1003144796589"

# =================================================


# Initialize MT5
if not mt5.initialize():
    print(f"MT5 initialization failed: {mt5.last_error()}")
    quit()

BROKER_TZ_OBJ = pytz.timezone(BROKER_TZ)


def send_telegram_message(text):
    """Send text message to Telegram group with bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"Telegram message failed: {response.text}")
    except Exception as e:
        print(f"Telegram sending error: {e}")


def fetch_current_price(symbol):
    """Fetch current price (midpoint) for symbol."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return (tick.ask + tick.bid) / 2


def _timeframe_str(tf):
    return {
        mt5.TIMEFRAME_M1: "M1",
        mt5.TIMEFRAME_M3: "M3",  # Added M3 since used in code (if unavailable in mt5, use string fallback)
        mt5.TIMEFRAME_M5: "M5",
        mt5.TIMEFRAME_M15: "M15",
        mt5.TIMEFRAME_M30: "M30",
        mt5.TIMEFRAME_H1: "H1",
        mt5.TIMEFRAME_D1: "D1"
    }.get(tf, str(tf))


def get_next_candle_close(tf):
    """Calculate next candle close time based on timeframe."""
    minute_map = {
        mt5.TIMEFRAME_M1: 1,
        mt5.TIMEFRAME_M3: 3,
        mt5.TIMEFRAME_M5: 5,
        mt5.TIMEFRAME_M15: 15,
        mt5.TIMEFRAME_M30: 30,
        mt5.TIMEFRAME_H1: 60
    }
    now = datetime.now(BROKER_TZ_OBJ)
    interval = minute_map.get(tf, 5)
    m = now.minute
    next_m = ((m // interval) + 1) * interval
    next_hour = now.hour
    next_day = now
    if next_m >= 60:
        next_m = 0
        next_hour += 1
        if next_hour >= 24:
            next_hour = 0
            next_day = now + timedelta(days=1)
        next_day = next_day.replace(hour=next_hour, minute=next_m, second=0, microsecond=0)
    else:
        next_day = now.replace(minute=next_m, second=0, microsecond=0)
    return next_day


def fetch_market_data(symbol, timeframe, count=150):
    rates = mt5.copy_rates_from(symbol, timeframe, datetime.now(), count)
    if rates is None:
        print(f"Failed to fetch data for {symbol} {_timeframe_str(timeframe)} : {mt5.last_error()}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


def calculate_ema(prices, period):
    return prices.ewm(span=period, adjust=False).mean()


def detect_crossover(df, short_period, long_period):
    """Detect EMA crossover signal. Returns 'BUY', 'SELL', or None."""
    df['ema_fast'] = calculate_ema(df['close'], short_period)
    df['ema_slow'] = calculate_ema(df['close'], long_period)
    prev_fast, prev_slow = df['ema_fast'].iat[-2], df['ema_slow'].iat[-2]
    curr_fast, curr_slow = df['ema_fast'].iat[-1], df['ema_slow'].iat[-1]
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return "BUY"
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        return "SELL"
    else:
        return None


def run_crossover_alert_bot():
    print(f"Starting EMA Crossover alert bot for symbols {SYMBOLS} on {_timeframe_str(TIMEFRAME1)} and {_timeframe_str(TIMEFRAME2)}")
    # Store last signals per symbol and per timeframe
    last_signals = {symbol: {TIMEFRAME1: None, TIMEFRAME2: None} for symbol in SYMBOLS}

    while True:
        now = datetime.now(BROKER_TZ_OBJ)
        nxt1 = get_next_candle_close(TIMEFRAME1)
        nxt2 = get_next_candle_close(TIMEFRAME2)
        next_close = min(nxt1, nxt2)
        wait_sec = max(0, (next_close - now).total_seconds())
        print(f"[{now.strftime('%H:%M:%S')}] Waiting {int(wait_sec)}s for candles to close...")
        time.sleep(wait_sec + 2)

        for symbol in SYMBOLS:
            # Timeframe 1
            df1 = fetch_market_data(symbol, TIMEFRAME1)
            if df1 is not None and len(df1) > LONG_EMA_PERIOD:
                signal1 = detect_crossover(df1, SHORT_EMA_PERIOD, LONG_EMA_PERIOD)
                if signal1 and signal1 != last_signals[symbol][TIMEFRAME1]:
                    msg = f"EMA {signal1} signal detected on {symbol} [{_timeframe_str(TIMEFRAME1)}] at {datetime.now(BROKER_TZ_OBJ).strftime('%Y-%m-%d %H:%M:%S')}"
                    print(msg)
                    send_telegram_message(msg)
                    last_signals[symbol][TIMEFRAME1] = signal1

            # Timeframe 2
            df2 = fetch_market_data(symbol, TIMEFRAME2)
            if df2 is not None and len(df2) > LONG_EMA_PERIOD:
                signal2 = detect_crossover(df2, SHORT_EMA_PERIOD, LONG_EMA_PERIOD)
                if signal2 and signal2 != last_signals[symbol][TIMEFRAME2]:
                    msg = f"EMA {signal2} signal detected on {symbol} [{_timeframe_str(TIMEFRAME2)}] at {datetime.now(BROKER_TZ_OBJ).strftime('%Y-%m-%d %H:%M:%S')}"
                    print(msg)
                    send_telegram_message(msg)
                    last_signals[symbol][TIMEFRAME2] = signal2


def listen_for_price_command():
    offset = None
    print("Listening for /price commands in group...")
    while True:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 100, "offset": offset}
        try:
            response = requests.get(url, params=params, timeout=120)
            updates = response.json()
            if updates and updates.get("result"):
                for update in updates["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update:
                        message = update["message"]
                        text = message.get("text", "").strip().lower()
                        if text.startswith("/price"):
                            parts = text.split()
                            # Allow optional symbol name after /price command
                            if len(parts) == 2 and parts[1].upper() in SYMBOLS:
                                symbol = parts[1].upper()
                            else:
                                # Default to first symbol if no or unknown symbol provided
                                symbol = SYMBOLS[0]
                            price = fetch_current_price(symbol)
                            if price:
                                reply = f"Current price of {symbol} is {price:.2f}"
                            else:
                                reply = f"Failed to fetch current price of {symbol}."
                            send_telegram_message(reply)
        except Exception as e:
            print(f"Error in command listener: {e}")
        time.sleep(1)


if __name__ == "__main__":
    threading.Thread(target=listen_for_price_command, daemon=True).start()
    run_crossover_alert_bot()
