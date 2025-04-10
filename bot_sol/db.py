import sqlite3
from datetime import datetime

DB_PATH = "trades.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            mode TEXT,
            symbol TEXT,
            side TEXT,
            price REAL,
            qty REAL,
            cost REAL,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_trade(trade_id, mode, symbol, side, price, qty):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO trades (id, mode, symbol, side, price, qty, cost, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_id,
        mode,
        symbol,
        side,
        price,
        qty,
        price * qty,
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()

def get_today_pnl(symbol):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    today = datetime.utcnow().date().isoformat()
    cursor.execute("""
        SELECT side, SUM(cost), COUNT(*)
        FROM trades
        WHERE date(timestamp) = ?
        GROUP BY side
    """, (today,))
    rows = cursor.fetchall()
    conn.close()

    total_buy = total_sell = qty = 0
    for row in rows:
        if row[0] == 'BUY':
            total_buy = row[1]
        elif row[0] == 'SELL':
            total_sell = row[1]
    pnl = (total_sell or 0) - (total_buy or 0)
    total_trades = sum(r[2] for r in rows)
    return pnl, total_trades

def get_pnl_history(symbol, limit=7):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date(timestamp), 
               SUM(CASE WHEN side='SELL' THEN cost ELSE 0 END) -
               SUM(CASE WHEN side='BUY' THEN cost ELSE 0 END) as pnl
        FROM trades
        GROUP BY date(timestamp)
        ORDER BY date(timestamp) DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return list(reversed(rows))
