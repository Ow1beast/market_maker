from telegram import ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler
from db import get_today_pnl, get_pnl_history
import os
import subprocess
import sys
from datetime import datetime

client = None
TRADE_MODE = None

GRID_LEVELS = 3
GRID_STEP = 0.25
ORDER_PCT = 0.1  # добавлено для расчета объема в сетке
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")


def start(update, context):
    keyboard = [
        ["/status", "/balance"],
        ["/pnl_today", "/pnl_table"],
        ["/restart"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("Команды:", reply_markup=reply_markup)

def pnl_today(update, context):
    pnl, count = get_today_pnl()
    update.message.reply_text(f"Сегодняшний PnL: {pnl:.2f} USDT\nСделок: {count}")

def pnl_table(update, context):
    rows = get_pnl_history(7)
    if not rows:
        update.message.reply_text("Нет данных.")
        return
    msg = "📊 История PnL за 7 дней:\n\n"
    for date_str, pnl in rows:
        pnl_fmt = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        msg += f"{date_str}  |  {pnl_fmt} USDT\n"
    update.message.reply_text(msg)

def get_balance():
    if TRADE_MODE == 'spot':
        balance = client.get_asset_balance(asset='USDT')
        return float(balance['free'])
    else:
        balances = client.futures_account_balance()
        for b in balances:
            if b['asset'] == 'USDT':
                return float(b['balance'])
        return 0.0

def save_daily_start_balance():
    today = datetime.now().strftime('%Y-%m-%d')
    path = f"start_balance_{today}.txt"
    if not os.path.exists(path):
        balance = get_balance()
        with open(path, "w") as f:
            f.write(str(balance))

def status(update, context):
    update.message.reply_text("✅ Бот работает.")

def restart(update, context):
    update.message.reply_text("♻️ Перезапуск бота (внутри контейнера)...")
    try:
        python = sys.executable
        os.execv(python, [python] + sys.argv)
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка при перезапуске: {e}")

def balance(update, context):
    try:
        usdt = get_balance()
        update.message.reply_text(f"💰 Баланс USDT: {usdt:.2f}\nРежим: {TRADE_MODE.upper()}")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка при получении баланса: {e}")

def run_bot(binance_client, trade_mode):
    global client, TRADE_MODE
    client = binance_client
    TRADE_MODE = trade_mode

    save_daily_start_balance()

    token = os.getenv("TG_TOKEN")
    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("pnl_today", pnl_today))
    dp.add_handler(CommandHandler("pnl_table", pnl_table))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("restart", restart))
    dp.add_handler(CommandHandler("balance", balance))

    updater.start_polling()

# ====== Сетка ордеров =======
def generate_grid_prices(mid_price, spread_step=GRID_STEP, levels=GRID_LEVELS):
    prices = []
    for i in range(1, levels + 1):
        buy = round(mid_price - i * spread_step, 2)
        sell = round(mid_price + i * spread_step, 2)
        prices.append((buy, sell))
    return prices

def place_grid_orders(mid_price):
    usdt = get_balance()
    qty = round((usdt * ORDER_PCT) / mid_price, 3)
    grid = generate_grid_prices(mid_price)

    for buy_price, sell_price in grid:
        try:
            if TRADE_MODE == 'spot':
                client.order_limit_buy(symbol=SYMBOL, quantity=qty, price=str(buy_price))
                client.order_limit_sell(symbol=SYMBOL, quantity=qty, price=str(sell_price))
            else:
                client.futures_create_order(symbol=SYMBOL, side='BUY', type='LIMIT', price=str(buy_price), quantity=qty, timeInForce='GTC')
                client.futures_create_order(symbol=SYMBOL, side='SELL', type='LIMIT', price=str(sell_price), quantity=qty, timeInForce='GTC')
        except Exception as e:
            print(f"Ошибка при размещении ордера: {e}")

# Вызов из основного цикла бота:
# вместо place_orders(bid, ask) — используем:
# mid_price = (bid + ask) / 2
# place_grid_orders(mid_price)
