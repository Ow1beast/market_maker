from telegram import ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler
from db import get_today_pnl, get_pnl_history
import os
import subprocess
import sys
from datetime import datetime

client_instances = {}
TRADE_MODES = {}

GRID_LEVELS = 3
GRID_STEP = 0.25
ORDER_PCT = 0.1

SYMBOLS = os.getenv("SYMBOLS", "BTCUSDT,SOLUSDT,ETHUSDT").split(',')


def start(update, context):
    keyboard = [
        ["/status ETHUSDT", "/balance ETHUSDT"],
        ["/pnl_today ETHUSDT", "/pnl_table ETHUSDT"],
        ["/restart ETHUSDT"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("Команды с указанием символа: например, /balance ETHUSDT", reply_markup=reply_markup)


def get_balance(symbol):
    client = client_instances[symbol]
    mode = TRADE_MODES[symbol]
    if mode == 'spot':
        balance = client.get_asset_balance(asset='USDT')
        return float(balance['free'])
    else:
        balances = client.futures_account_balance()
        for b in balances:
            if b['asset'] == 'USDT':
                return float(b['balance'])
        return 0.0


def save_daily_start_balance(symbol):
    today = datetime.now().strftime('%Y-%m-%d')
    path = f"start_balance_{symbol}_{today}.txt"
    if not os.path.exists(path):
        balance = get_balance(symbol)
        with open(path, "w") as f:
            f.write(str(balance))


def status(update, context):
    if context.args:
        symbol = context.args[0].upper()
        update.message.reply_text(f"✅ Бот для {symbol} работает.")
    else:
        update.message.reply_text("Укажи символ: /status ETHUSDT")


def restart(update, context):
    if context.args:
        symbol = context.args[0].upper()
        service = f"marketmaker-{symbol.lower()}.service"
        os.system(f"sudo systemctl restart {service}")
        update.message.reply_text(f"♻️ Перезапущен бот {symbol}")
    else:
        update.message.reply_text("Укажи символ: /restart ETHUSDT")


def balance(update, context):
    if context.args:
        symbol = context.args[0].upper()
        try:
            usdt = get_balance(symbol)
            update.message.reply_text(f"💰 Баланс USDT для {symbol}: {usdt:.2f}")
        except Exception as e:
            update.message.reply_text(f"❌ Ошибка: {e}")
    else:
        update.message.reply_text("Укажи символ: /balance ETHUSDT")


def pnl_today(update, context):
    if context.args:
        symbol = context.args[0].upper()
        pnl, count = get_today_pnl(symbol)
        update.message.reply_text(f"Сегодняшний PnL для {symbol}: {pnl:.2f} USDT\nСделок: {count}")
    else:
        update.message.reply_text("Укажи символ: /pnl_today ETHUSDT")


def pnl_table(update, context):
    if context.args:
        symbol = context.args[0].upper()
        rows = get_pnl_history(symbol, 7)
        if not rows:
            update.message.reply_text("Нет данных.")
            return
        msg = f"📊 История PnL по {symbol} за 7 дней:\n\n"
        for date_str, pnl in rows:
            pnl_fmt = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
            msg += f"{date_str}  |  {pnl_fmt} USDT\n"
        update.message.reply_text(msg)
    else:
        update.message.reply_text("Укажи символ: /pnl_table ETHUSDT")


def run_bot(bot_token, clients_dict, trade_modes_dict):
    global client_instances, TRADE_MODES
    client_instances = clients_dict
    TRADE_MODES = trade_modes_dict

    updater = Updater(bot_token, use_context=True)
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

def place_grid_orders(client, trade_mode, symbol, mid_price, order_pct):
    from loguru import logger
    usdt = float(get_balance(symbol))
    qty = round((usdt * order_pct) / mid_price, 3)
    step = 0.25
    levels = 3
    for i in range(1, levels + 1):
        buy_price = round(mid_price - i * step, 2)
        sell_price = round(mid_price + i * step, 2)
        try:
            if trade_mode == 'spot':
                client.order_limit_buy(symbol=symbol, quantity=qty, price=str(buy_price))
                client.order_limit_sell(symbol=symbol, quantity=qty, price=str(sell_price))
            else:
                client.futures_create_order(symbol=symbol, side='BUY', type='LIMIT', price=str(buy_price), quantity=qty, timeInForce='GTC')
                client.futures_create_order(symbol=symbol, side='SELL', type='LIMIT', price=str(sell_price), quantity=qty, timeInForce='GTC')
            logger.info(f"[{symbol}] Ордер BUY {buy_price}, SELL {sell_price}, QTY {qty}")
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка при размещении ордера: {e}")
