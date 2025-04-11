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
from bot_commands import run_bot, get_balance, place_grid_orders

# === Загрузка .env ===
load_dotenv()

# === Универсальная инициализация клиентов ===
clients = {}
modes = {}
symbols = os.getenv("SYMBOLS", "BTCUSDT,SOLUSDT").split(',')

for symbol in symbols:
    api_key = os.getenv(f"{symbol}_API_KEY")
    api_secret = os.getenv(f"{symbol}_API_SECRET")
    trade_mode = os.getenv(f"{symbol}_MODE", "spot").lower()
    client = Client(api_key, api_secret)

    if os.getenv(f"{symbol}_TESTNET", "false").lower() == "true":
        if trade_mode == "futures":
            client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
        else:
            client.API_URL = "https://testnet.binance.vision/api"

    clients[symbol] = client
    modes[symbol] = trade_mode

TG_TOKEN = os.getenv("TG_TOKEN")
ORDER_PCT = float(os.getenv("ORDER_PCT", "0.1"))
INTERVAL = int(os.getenv("INTERVAL", "5"))
TAKE_PROFIT = float(os.getenv("TAKE_PROFIT", "99999"))
STOP_LOSS = float(os.getenv("STOP_LOSS", "-99999"))

# === PnL-состояние для каждого символа ===
session_start_ids = {}
session_trades = {}

# === Telegram ===
def send_telegram(message):
    chat_id = os.getenv("TG_CHAT_ID")
    if not TG_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": message})
    except Exception as e:
        logger.error(f"[Telegram] Ошибка: {e}")

# === Получение стакана ===
async def get_order_book(symbol, trade_mode, use_testnet):
    if use_testnet:
        url = f'wss://stream.binance.vision/ws/{symbol.lower()}@depth5@100ms' if trade_mode == 'spot' \
              else f'wss://stream.binancefuture.com/ws/{symbol.lower()}@depth5@100ms'
    else:
        url = f'wss://stream.binance.com:9443/ws/{symbol.lower()}@depth5@100ms' if trade_mode == 'spot' \
              else f'wss://fstream.binance.com/ws/{symbol.lower()}@depth5@100ms'

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg.data)
                    if 'bids' in data and 'asks' in data:
                        bid = float(data['bids'][0][0])
                        ask = float(data['asks'][0][0])
                        return bid, ask
                    else:
                        continue  # пропускаем пустые или системные сообщения
                except Exception as e:
                    logger.warning(f"[{symbol}] Невалидное сообщение в стакане: {e}")


# === PnL логика ===
def get_last_trade_id(symbol):
    file = f"last_trade_id_{symbol}.txt"
    if os.path.exists(file):
        with open(file, "r") as f:
            return int(f.read())
    return 0

def save_last_trade_id(symbol, trade_id):
    with open(f"last_trade_id_{symbol}.txt", "w") as f:
        f.write(str(trade_id))

def track_trades_and_pnl(symbol):
    client = clients[symbol]
    trade_mode = modes[symbol]

    trades = client.get_my_trades(symbol=symbol) if trade_mode == 'spot' else client.futures_account_trades(symbol=symbol)
    last_saved_id = get_last_trade_id(symbol)
    new_trades = [t for t in trades if t['id'] > last_saved_id]
    if not new_trades:
        return
    save_last_trade_id(symbol, new_trades[-1]['id'])

    if symbol not in session_trades:
        session_trades[symbol] = []

    total_buy = total_sell = qty_buy = qty_sell = 0
    for t in new_trades:
        qty = float(t['qty'])
        price = float(t['price'])
        cost = qty * price
        is_buy = t['isBuyer'] if trade_mode == 'spot' else t['side'] == 'BUY'
        if is_buy:
            total_buy += cost
            qty_buy += qty
        else:
            total_sell += cost
            qty_sell += qty
        if t['id'] >= session_start_ids[symbol]:
            side = 'BUY' if is_buy else 'SELL'
            save_trade(t['id'], trade_mode, symbol, side, float(t['price']), float(t['qty']))
            session_trades[symbol].append(t)

    sb = ss = sqb = sqs = 0
    for t in session_trades[symbol]:
        qty = float(t['qty'])
        price = float(t['price'])
        cost = qty * price
        is_buy = t['isBuyer'] if trade_mode == 'spot' else t['side'] == 'BUY'
        if is_buy:
            sb += cost
            sqb += qty
        else:
            ss += cost
            sqs += qty

    pnl = ss - sb
    msg = (
        f"[{symbol}] Сессия PnL\n"
        f"Покупка: {sqb:.4f} на {sb:.2f} USDT\n"
        f"Продажа: {sqs:.4f} на {ss:.2f} USDT\n"
        f"→ PnL: {pnl:.2f} USDT"
    )
    logger.info(msg)
    send_telegram(msg)

    if pnl >= TAKE_PROFIT:
        send_telegram(f"[STOP {symbol}] Профит достигнут: {pnl:.2f} USDT")
        exit(0)
    if pnl <= STOP_LOSS:
        send_telegram(f"[STOP {symbol}] Убыток достигнут: {pnl:.2f} USDT")
        exit(0)

# === Основной цикл по символу ===
async def run_symbol(symbol):
    client = clients[symbol]
    trade_mode = modes[symbol]
    use_testnet = os.getenv(f"{symbol}_TESTNET", "false").lower() == "true"

    session_start_ids[symbol] = get_last_trade_id(symbol)

    while True:
        try:
            bid, ask = await get_order_book(symbol, trade_mode, use_testnet)
            mid_price = (bid + ask) / 2
            usdt = get_balance(symbol)
            order_value = usdt * ORDER_PCT
            qty = round(order_value / mid_price, 6)
            send_telegram(f"[{symbol}] Баланс: {usdt:.2f} USDT, Ордер на: {order_value:.2f} USDT ({qty:.6f} {symbol[:-4]})")
            place_grid_orders(client, trade_mode, symbol, mid_price, ORDER_PCT)
            track_trades_and_pnl(symbol)
            await asyncio.sleep(INTERVAL)
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка: {e}")
            await asyncio.sleep(5)

# === Запуск Telegram и торговли ===
if __name__ == '__main__':
    init_db()
    logger.info(f"[Старт] Универсальный Telegram-бот запущен для: {', '.join(symbols)}")
    Thread(target=run_bot, args=(TG_TOKEN, clients, modes)).start()
    loop = asyncio.get_event_loop()
    tasks = [run_symbol(symbol) for symbol in symbols]
    loop.run_until_complete(asyncio.gather(*tasks))
