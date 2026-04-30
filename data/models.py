"""SQLite数据模型定义与数据库初始化"""

import sqlite3
from datetime import datetime


# 14张表的DDL定义
DDL_STATEMENTS = [
    # LOF基金基础信息表
    """CREATE TABLE IF NOT EXISTS lof_fund (
        code TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'normal',
        is_suspended INTEGER NOT NULL DEFAULT 0,
        daily_volume REAL NOT NULL DEFAULT 0.0,
        muted_until TEXT NOT NULL DEFAULT '',
        mute_reason TEXT NOT NULL DEFAULT '',
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
    # 数据源状态表（扩展：增加失败时间和失败原因）
    """CREATE TABLE IF NOT EXISTS data_source_status (
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'unknown',
        last_success_time TEXT NOT NULL DEFAULT '',
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_failure_time TEXT NOT NULL DEFAULT '',
        failure_reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (name)
    )""",
    # 策略执行日志表
    """CREATE TABLE IF NOT EXISTS strategy_execution_log (
        id INTEGER NOT NULL,
        strategy_name TEXT NOT NULL DEFAULT '',
        trigger_time TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'success',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        error_message TEXT NOT NULL DEFAULT '',
        record_time TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 告警事件表
    """CREATE TABLE IF NOT EXISTS alert_event (
        id INTEGER NOT NULL,
        level TEXT NOT NULL DEFAULT 'INFO',
        source TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        timestamp TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 通知发送记录表
    """CREATE TABLE IF NOT EXISTS notification_log (
        id INTEGER NOT NULL,
        channel TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'success',
        timestamp TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 系统状态KV表
    """CREATE TABLE IF NOT EXISTS system_status (
        key TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (key)
    )""",
    # 配置键值存储表
    """CREATE TABLE IF NOT EXISTS config_kv (
        category TEXT NOT NULL DEFAULT '',
        section TEXT NOT NULL DEFAULT '',
        key TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL DEFAULT '',
        value_type TEXT NOT NULL DEFAULT 'string',
        label TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        create_time TEXT NOT NULL DEFAULT '',
        update_time TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (category, section, key)
    )""",
    # 配置重载信号表（跨进程通信）
    """CREATE TABLE IF NOT EXISTS config_reload_signal (
        id INTEGER NOT NULL,
        signal_time TEXT NOT NULL DEFAULT '',
        processed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
]

# 索引定义
INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_premium_history_code ON premium_history(fund_code)",
    "CREATE INDEX IF NOT EXISTS idx_premium_history_ts ON premium_history(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_trade_signal_code ON trade_signal(fund_code)",
    "CREATE INDEX IF NOT EXISTS idx_holiday_date ON holiday_calendar(date)",
    "CREATE INDEX IF NOT EXISTS idx_execution_log_strategy ON strategy_execution_log(strategy_name)",
    "CREATE INDEX IF NOT EXISTS idx_execution_log_time ON strategy_execution_log(trigger_time)",
    "CREATE INDEX IF NOT EXISTS idx_alert_event_time ON alert_event(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_notification_log_time ON notification_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_config_kv_category ON config_kv(category)",
    "CREATE INDEX IF NOT EXISTS idx_config_reload_unprocessed ON config_reload_signal(processed)",
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
    "strategy_execution_log",
    "alert_event",
    "notification_log",
    "system_status",
    "config_kv",
    "config_reload_signal",
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
    # 兼容已有数据库：尝试添加新字段
    for stmt in [
        "ALTER TABLE data_source_status ADD COLUMN last_failure_time TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE data_source_status ADD COLUMN failure_reason TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE lof_fund ADD COLUMN muted_until TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE lof_fund ADD COLUMN mute_reason TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            cursor.execute(stmt)
        except Exception:
            pass  # 字段已存在则忽略
    conn.commit()
