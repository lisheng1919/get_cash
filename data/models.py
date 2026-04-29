"""SQLite数据模型定义与数据库初始化"""

import sqlite3
from datetime import datetime


# 10张表的DDL定义
DDL_STATEMENTS = [
    # LOF基金基础信息表
    """CREATE TABLE IF NOT EXISTS lof_fund (
        code TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'normal',
        is_suspended INTEGER NOT NULL DEFAULT 0,
        daily_volume REAL NOT NULL DEFAULT 0.0,
        updated_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (code)
    )""",
    # 溢价率历史表
    """CREATE TABLE IF NOT EXISTS premium_history (
        id INTEGER NOT NULL,
        timestamp TEXT NOT NULL DEFAULT '',
        fund_code TEXT NOT NULL DEFAULT '',
        price REAL NOT NULL DEFAULT 0.0,
        iopv REAL NOT NULL DEFAULT 0.0,
        premium_rate REAL NOT NULL DEFAULT 0.0,
        iopv_source TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 交易信号表
    """CREATE TABLE IF NOT EXISTS trade_signal (
        id INTEGER NOT NULL,
        trigger_time TEXT NOT NULL DEFAULT '',
        fund_code TEXT NOT NULL DEFAULT '',
        premium_rate REAL NOT NULL DEFAULT 0.0,
        action TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        iopv_source TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 持仓表
    """CREATE TABLE IF NOT EXISTS position (
        fund_code TEXT NOT NULL DEFAULT '',
        shares INTEGER NOT NULL DEFAULT 0,
        cost_price REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY (fund_code)
    )""",
    # 债券IPO表
    """CREATE TABLE IF NOT EXISTS bond_ipo (
        code TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        subscribe_date TEXT NOT NULL DEFAULT '',
        winning_result TEXT NOT NULL DEFAULT '',
        payment_status TEXT NOT NULL DEFAULT 'pending',
        listing_date TEXT NOT NULL DEFAULT '',
        sell_status TEXT NOT NULL DEFAULT 'pending',
        PRIMARY KEY (code)
    )""",
    # 债券配债表
    """CREATE TABLE IF NOT EXISTS bond_allocation (
        code TEXT NOT NULL DEFAULT '',
        stock_code TEXT NOT NULL DEFAULT '',
        stock_name TEXT NOT NULL DEFAULT '',
        content_weight REAL NOT NULL DEFAULT 0.0,
        safety_cushion REAL NOT NULL DEFAULT 0.0,
        record_date TEXT NOT NULL DEFAULT '',
        payment_date TEXT NOT NULL DEFAULT '',
        listing_date TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        actual_slippage REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY (code)
    )""",
    # 逆回购表
    """CREATE TABLE IF NOT EXISTS reverse_repo (
        id INTEGER NOT NULL,
        date TEXT NOT NULL DEFAULT '',
        code TEXT NOT NULL DEFAULT '',
        rate REAL NOT NULL DEFAULT 0.0,
        amount REAL NOT NULL DEFAULT 0.0,
        due_date TEXT NOT NULL DEFAULT '',
        profit REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 节假日日历表
    """CREATE TABLE IF NOT EXISTS holiday_calendar (
        date TEXT NOT NULL DEFAULT '',
        is_trading_day INTEGER NOT NULL DEFAULT 0,
        is_pre_holiday INTEGER NOT NULL DEFAULT 0,
        holiday_name TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (date)
    )""",
    # 每日汇总表
    """CREATE TABLE IF NOT EXISTS daily_summary (
        id INTEGER NOT NULL,
        date TEXT NOT NULL DEFAULT '',
        strategy_type TEXT NOT NULL DEFAULT '',
        profit REAL NOT NULL DEFAULT 0.0,
        action_log TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 数据源状态表
    """CREATE TABLE IF NOT EXISTS data_source_status (
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'unknown',
        last_success_time TEXT NOT NULL DEFAULT '',
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (name)
    )""",
]

# 索引定义
INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_premium_history_code ON premium_history(fund_code)",
    "CREATE INDEX IF NOT EXISTS idx_premium_history_ts ON premium_history(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_trade_signal_code ON trade_signal(fund_code)",
    "CREATE INDEX IF NOT EXISTS idx_holiday_date ON holiday_calendar(date)",
]

# 所有表名列表
TABLE_NAMES = [
    "lof_fund",
    "premium_history",
    "trade_signal",
    "position",
    "bond_ipo",
    "bond_allocation",
    "reverse_repo",
    "holiday_calendar",
    "daily_summary",
    "data_source_status",
]


def init_db(conn: sqlite3.Connection) -> None:
    """初始化数据库：创建所有表和索引

    Args:
        conn: sqlite3数据库连接
    """
    cursor = conn.cursor()
    # 创建所有表
    for ddl in DDL_STATEMENTS:
        cursor.execute(ddl)
    # 创建所有索引
    for idx_sql in INDEX_STATEMENTS:
        cursor.execute(idx_sql)
    conn.commit()
