# main_bot.py
import asyncio
import json
import aiohttp
import os
import requests
from dotenv import load_dotenv
from binance.client import Client
from datetime import datetime
from loguru import logger
from db import init_db, save_trade
from threading import Thread
from bot_commands import run_bot

# === Загрузка .env ===
load_dotenv()
API_KEY = os.getenv("LIVE_API_KEY")
API_SECRET = os.getenv("LIVE_API_SECRET")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
TRADE_MODE = os.getenv("TRADE_MODE", "futures").lower()
SYMBOL = 'BTCUSDT'
BASE_SPREAD = 0.0004
ORDER_PCT = 0.1
INTERVAL = 5
TAKE_PROFIT = float(os.getenv("TAKE_PROFIT", "99999"))
STOP_LOSS = float(os.getenv("STOP_LOSS", "-99999"))
TRADE_LOG_FILE = os.getenv("TRADE_LOG_FILE", "last_trade_id.txt")
SYSTEMD_SERVICE = os.getenv("SYSTEMD_SERVICE", "marketmaker.service")

client = Client(API_KEY, API_SECRET)

if os.getenv("TESTNET") == "true":
    if TRADE_MODE == "futures":
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
    else:
        client.API_URL = "https://testnet.binance.vision/api"

os.makedirs("logs", exist_ok=True)
log_file = f"logs/{datetime.now().strftime('%Y-%m-%d')}_{TRADE_MODE}.log"
logger.add(log_file, rotation="5 MB", retention="7 days", encoding='utf-8')

# === Telegram ===
def send_telegram(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": message})
    except Exception as e:
        logger.error(f"[Telegram] Ошибка: {e}")

# === Получение рыночных данных ===
async def get_order_book():
    url = f'wss://stream.binance.com:9443/ws/{SYMBOL.lower()}@depth5@100ms' if TRADE_MODE == 'spot' else f'wss://fstream.binance.com/ws/{SYMBOL.lower()}@depth5@100ms'
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            async for msg in ws:
                data = json.loads(msg.data)
                bid = float(data['bids'][0][0])
                ask = float(data['asks'][0][0])
                return bid, ask

def calculate_order_amount(price):
    usdt = get_balance()
    return round((usdt * ORDER_PCT) / price, 3)

# === Ордеры ===
def cancel_orders():
    if TRADE_MODE == 'spot':
        orders = client.get_open_orders(symbol=SYMBOL)
        for o in orders:
            client.cancel_order(symbol=SYMBOL, orderId=o['orderId'])
    else:
        client.futures_cancel_all_open_orders(symbol=SYMBOL)
    logger.info("[Ордера] Все заявки отменены")

def place_orders(bid, ask):
    mid_price = (bid + ask) / 2
    spread = max(mid_price * BASE_SPREAD, 0.5)
    buy_price = round(mid_price - spread, 1)
    sell_price = round(mid_price + spread, 1)
    qty = calculate_order_amount(mid_price)

    if TRADE_MODE == 'spot':
        client.order_limit_buy(symbol=SYMBOL, quantity=qty, price=str(buy_price))
        client.order_limit_sell(symbol=SYMBOL, quantity=qty, price=str(sell_price))
    else:
        client.futures_create_order(symbol=SYMBOL, side='BUY', type='LIMIT', price=str(buy_price), quantity=qty, timeInForce='GTC')
        client.futures_create_order(symbol=SYMBOL, side='SELL', type='LIMIT', price=str(sell_price), quantity=qty, timeInForce='GTC')

    logger.info(f"[Ордера] BUY {buy_price}, SELL {sell_price}, QTY {qty}")
    send_telegram(f"[{TRADE_MODE.upper()}] BUY {buy_price}, SELL {sell_price}, QTY {qty}")

# === PnL логика ===
def get_last_trade_id():
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "r") as f:
            return int(f.read())
    return 0

def save_last_trade_id(trade_id):
    with open(TRADE_LOG_FILE, "w") as f:
        f.write(str(trade_id))

SESSION_START_ID = get_last_trade_id()
SESSION_TRADES = []

def track_trades_and_pnl():
    global SESSION_TRADES
    trades = client.get_my_trades(symbol=SYMBOL) if TRADE_MODE == 'spot' else client.futures_account_trades(symbol=SYMBOL)
    last_saved_id = get_last_trade_id()
    new_trades = [t for t in trades if t['id'] > last_saved_id]
    if not new_trades:
        return
    save_last_trade_id(new_trades[-1]['id'])

    total_buy = total_sell = qty_buy = qty_sell = 0
    for t in new_trades:
        qty = float(t['qty'])
        price = float(t['price'])
        cost = qty * price
        if t['isBuyer'] if TRADE_MODE == 'spot' else t['side'] == 'BUY':
            total_buy += cost
            qty_buy += qty
        else:
            total_sell += cost
            qty_sell += qty
        if t['id'] >= SESSION_START_ID:
            side = 'BUY' if (t['isBuyer'] if TRADE_MODE == 'spot' else t['side'] == 'BUY') else 'SELL'
            save_trade(t['id'], TRADE_MODE, SYMBOL, side, float(t['price']), float(t['qty']))
            SESSION_TRADES.append(t)

    session_buy = session_sell = session_qty_buy = session_qty_sell = 0
    for t in SESSION_TRADES:
        qty = float(t['qty'])
        price = float(t['price'])
        cost = qty * price
        if t['isBuyer'] if TRADE_MODE == 'spot' else t['side'] == 'BUY':
            session_buy += cost
            session_qty_buy += qty
        else:
            session_sell += cost
            session_qty_sell += qty

    session_pnl = session_sell - session_buy
    msg = (
        f"[Сессия PnL]\n"
        f"Покупка: {session_qty_buy:.4f} на {session_buy:.2f} USDT\n"
        f"Продажа: {session_qty_sell:.4f} на {session_sell:.2f} USDT\n"
        f"→ PnL сессии: {session_pnl:.2f} USDT"
    )
    logger.info(msg)
    send_telegram(msg)

    if session_pnl >= TAKE_PROFIT:
        send_telegram(f"[STOP] Достигнут профит {session_pnl:.2f} USDT — бот остановлен")
        exit(0)
    if session_pnl <= STOP_LOSS:
        send_telegram(f"[STOP] Достигнут лимит убытка {session_pnl:.2f} USDT — бот остановлен")
        exit(0)

# === Основной цикл ===
async def main_loop():
    while True:
        try:
            bid, ask = await get_order_book()
            cancel_orders()
            place_orders(bid, ask)
            track_trades_and_pnl()
            await asyncio.sleep(INTERVAL)
        except Exception as e:
            logger.error(f"[Ошибка] {e}")
            send_telegram(f"[Ошибка] {e}")
            await asyncio.sleep(5)

if __name__ == '__main__':
    init_db()
    logger.info(f"[Старт] Бот запущен в режиме {TRADE_MODE.upper()}")
    send_telegram(f"Маркет-мейкер запущен. Режим: {TRADE_MODE.upper()}, trade_id: {SESSION_START_ID}")
    Thread(target=run_bot).start()
    asyncio.run(main_loop())
