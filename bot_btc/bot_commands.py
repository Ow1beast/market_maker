from telegram.ext import Updater, CommandHandler
from db import get_today_pnl, get_pnl_history
import os
import subprocess

def start(update, context):
    update.message.reply_text("Команды: /status /pnl_today /pnl_table /restart")

def pnl_today(update, context):
    pnl, count = get_today_pnl()
    msg = f"Сегодняшний PnL: {pnl:.2f} USDT\nСделок: {count}"
    update.message.reply_text(msg)

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

def run_bot():
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
    updater.idle()
