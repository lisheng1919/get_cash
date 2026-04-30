"""数据存储层，提供对SQLite数据库的CRUD操作"""

import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional


class Storage:
    """数据存储类，封装所有数据库操作

    通过构造函数接收sqlite3.Connection，不持有全局连接。
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        # 使用Row工厂以便通过列名访问
        self._conn.row_factory = sqlite3.Row

    # ==================== LOF基金 ====================

    def upsert_lof_fund(self, code: str, name: str, status: str = "normal",
                        is_suspended: bool = False, daily_volume: float = 0.0) -> None:
        """插入或更新LOF基金信息"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute(
            """INSERT INTO lof_fund (code, name, status, is_suspended, daily_volume, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                   name=excluded.name,
                   status=excluded.status,
                   is_suspended=excluded.is_suspended,
                   daily_volume=excluded.daily_volume,
                   updated_at=excluded.updated_at""",
            (code, name, status, int(is_suspended), daily_volume, now),
        )
        self._conn.commit()

    def get_lof_fund(self, code: str) -> Optional[Dict]:
        """根据代码获取LOF基金信息"""
        cursor = self._conn.execute(
            "SELECT * FROM lof_fund WHERE code = ?", (code,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def mute_fund(self, code: str, muted_until: str, reason: str = "") -> None:
        """设置基金静默状态

        Args:
            code: 基金代码
            muted_until: 静默到期时间，格式 YYYY-MM-DD HH:MM:SS
            reason: 静默原因
        """
        self._conn.execute(
            """UPDATE lof_fund SET status='muted', muted_until=?, mute_reason=?
               WHERE code=?""",
            (muted_until, reason, code),
        )
        self._conn.commit()

    def unmute_fund(self, code: str) -> None:
        """解除基金静默状态，恢复正常

        Args:
            code: 基金代码
        """
        self._conn.execute(
            """UPDATE lof_fund SET status='normal', muted_until='', mute_reason=''
               WHERE code=?""",
            (code,),
        )
        self._conn.commit()

    def list_muted_funds(self) -> List[Dict]:
        """查询所有静默中的基金"""
        cursor = self._conn.execute(
            "SELECT * FROM lof_fund WHERE status='muted'"
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 溢价率历史 ====================

    def insert_premium_history(self, timestamp: str, fund_code: str,
                               price: float, iopv: float, premium_rate: float,
                               iopv_source: str = "") -> int:
        """插入溢价率历史记录，返回自增ID"""
        cursor = self._conn.execute(
            """INSERT INTO premium_history (timestamp, fund_code, price, iopv, premium_rate, iopv_source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (timestamp, fund_code, price, iopv, premium_rate, iopv_source),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_premium_history(self, fund_code: str, limit: int = 100) -> List[Dict]:
        """获取指定基金的溢价率历史，按时间倒序"""
        cursor = self._conn.execute(
            """SELECT * FROM premium_history
               WHERE fund_code = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (fund_code, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 交易信号 ====================

    def insert_trade_signal(self, trigger_time: str, fund_code: str,
                            premium_rate: float, action: str,
                            status: str = "pending", iopv_source: str = "") -> int:
        """插入交易信号，返回自增ID"""
        cursor = self._conn.execute(
            """INSERT INTO trade_signal (trigger_time, fund_code, premium_rate, action, status, iopv_source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trigger_time, fund_code, premium_rate, action, status, iopv_source),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_trade_signals(self, fund_code: str = "", limit: int = 100) -> List[Dict]:
        """获取交易信号列表，可按基金代码过滤"""
        if fund_code:
            cursor = self._conn.execute(
                """SELECT * FROM trade_signal
                   WHERE fund_code = ?
                   ORDER BY trigger_time DESC
                   LIMIT ?""",
                (fund_code, limit),
            )
        else:
            cursor = self._conn.execute(
                """SELECT * FROM trade_signal
                   ORDER BY trigger_time DESC
                   LIMIT ?""",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 节假日日历 ====================

    def upsert_holiday(self, date_str: str, is_trading_day: bool,
                       is_pre_holiday: bool = False, holiday_name: str = "") -> None:
        """插入或更新节假日日历记录"""
        self._conn.execute(
            """INSERT INTO holiday_calendar (date, is_trading_day, is_pre_holiday, holiday_name)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                   is_trading_day=excluded.is_trading_day,
                   is_pre_holiday=excluded.is_pre_holiday,
                   holiday_name=excluded.holiday_name""",
            (date_str, int(is_trading_day), int(is_pre_holiday), holiday_name),
        )
        self._conn.commit()

    def upsert_holidays_batch(self, records: list) -> None:
        """批量写入节假日记录，一次性提交

        Args:
            records: 列表，每项为 (date_str, is_trading_day, is_pre_holiday, holiday_name) 元组
        """
        if not records:
            return
        self._conn.executemany(
            """INSERT INTO holiday_calendar (date, is_trading_day, is_pre_holiday, holiday_name)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                   is_trading_day=excluded.is_trading_day,
                   is_pre_holiday=excluded.is_pre_holiday,
                   holiday_name=excluded.holiday_name""",
            records,
        )
        self._conn.commit()

    def is_pre_holiday(self, date_str: str) -> bool:
        """判断指定日期是否为节前交易日"""
        cursor = self._conn.execute(
            "SELECT is_pre_holiday FROM holiday_calendar WHERE date = ?",
            (date_str,),
        )
        row = cursor.fetchone()
        # 无记录时返回False
        if row is None:
            return False
        return bool(row["is_pre_holiday"])

    def is_trading_day(self, date_str: str) -> bool:
        """判断指定日期是否为交易日

        无记录时按周末判断：周六(5)和周日(6)非交易日，其余为交易日。
        """
        cursor = self._conn.execute(
            "SELECT is_trading_day FROM holiday_calendar WHERE date = ?",
            (date_str,),
        )
        row = cursor.fetchone()
        if row is not None:
            return bool(row["is_trading_day"])
        # 无记录：按周末判断
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # weekday(): 周一=0, 周日=6
        return dt.weekday() < 5

    # ==================== 数据源状态 ====================

    def update_data_source_status(self, name: str, status: str) -> None:
        """更新数据源状态（成功时调用，重置失败计数）"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute(
            """INSERT INTO data_source_status (name, status, last_success_time, consecutive_failures)
               VALUES (?, ?, ?, 0)
               ON CONFLICT(name) DO UPDATE SET
                   status=excluded.status,
                   last_success_time=excluded.last_success_time,
                   consecutive_failures=0""",
            (name, status, now),
        )
        self._conn.commit()

    def get_data_source_status(self, name: str) -> Optional[Dict]:
        """获取数据源状态"""
        cursor = self._conn.execute(
            "SELECT * FROM data_source_status WHERE name = ?", (name,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def record_data_source_failure(self, name: str, reason: str = "") -> int:
        """记录数据源失败，连续失败次数+1，返回当前失败次数

        Args:
            name: 数据源名称
            reason: 失败原因，截断至200字符
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 先查询当前状态
        cursor = self._conn.execute(
            "SELECT consecutive_failures FROM data_source_status WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            # 不存在则插入初始记录
            self._conn.execute(
                """INSERT INTO data_source_status (name, status, last_success_time, consecutive_failures, last_failure_time, failure_reason)
                   VALUES (?, 'failure', '', 1, ?, ?)""",
                (name, now, reason[:200]),
            )
            self._conn.commit()
            return 1
        # 更新失败次数
        new_count = row["consecutive_failures"] + 1
        self._conn.execute(
            """UPDATE data_source_status
               SET status='failure', consecutive_failures=?, last_failure_time=?, failure_reason=?
               WHERE name=?""",
            (new_count, now, reason[:200], name),
        )
        self._conn.commit()
        return new_count

    def list_all_data_source_status(self) -> List[Dict]:
        """列出所有数据源状态"""
        cursor = self._conn.execute(
            "SELECT * FROM data_source_status ORDER BY name"
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 债券IPO ====================

    def upsert_bond_ipo(self, code: str, name: str, subscribe_date: str = "",
                        winning_result: str = "", payment_status: str = "pending",
                        listing_date: str = "", sell_status: str = "pending") -> None:
        """插入或更新债券IPO信息"""
        self._conn.execute(
            """INSERT INTO bond_ipo (code, name, subscribe_date, winning_result, payment_status, listing_date, sell_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                   name=excluded.name,
                   subscribe_date=excluded.subscribe_date,
                   winning_result=excluded.winning_result,
                   payment_status=excluded.payment_status,
                   listing_date=excluded.listing_date,
                   sell_status=excluded.sell_status""",
            (code, name, subscribe_date, winning_result, payment_status, listing_date, sell_status),
        )
        self._conn.commit()

    def get_pending_bond_ipo(self) -> List[Dict]:
        """获取所有待处理的债券IPO（payment_status为pending）"""
        cursor = self._conn.execute(
            """SELECT * FROM bond_ipo WHERE payment_status = 'pending'
               ORDER BY subscribe_date""",
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 债券配债 ====================

    def upsert_bond_allocation(self, code: str, stock_code: str, stock_name: str,
                               content_weight: float = 0.0, safety_cushion: float = 0.0,
                               record_date: str = "", payment_date: str = "",
                               listing_date: str = "", status: str = "pending",
                               actual_slippage: float = 0.0) -> None:
        """插入或更新债券配债信息"""
        self._conn.execute(
            """INSERT INTO bond_allocation (code, stock_code, stock_name, content_weight,
                   safety_cushion, record_date, payment_date, listing_date, status, actual_slippage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                   stock_code=excluded.stock_code,
                   stock_name=excluded.stock_name,
                   content_weight=excluded.content_weight,
                   safety_cushion=excluded.safety_cushion,
                   record_date=excluded.record_date,
                   payment_date=excluded.payment_date,
                   listing_date=excluded.listing_date,
                   status=excluded.status,
                   actual_slippage=excluded.actual_slippage""",
            (code, stock_code, stock_name, content_weight, safety_cushion,
             record_date, payment_date, listing_date, status, actual_slippage),
        )
        self._conn.commit()

    def get_upcoming_allocations(self, days: int = 7) -> List[Dict]:
        """获取近期即将到来的配债记录（status为pending且record_date在未来N天内）"""
        today = date.today().strftime("%Y-%m-%d")
        cursor = self._conn.execute(
            """SELECT * FROM bond_allocation
               WHERE status = 'pending' AND record_date >= ?
               ORDER BY record_date""",
            (today,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 逆回购 ====================

    def insert_reverse_repo(self, date_str: str, code: str, rate: float,
                            amount: float, due_date: str, profit: float = 0.0) -> int:
        """插入逆回购记录，返回自增ID"""
        cursor = self._conn.execute(
            """INSERT INTO reverse_repo (date, code, rate, amount, due_date, profit)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (date_str, code, rate, amount, due_date, profit),
        )
        self._conn.commit()
        return cursor.lastrowid

    # ==================== 每日汇总 ====================

    def insert_daily_summary(self, date_str: str, strategy_type: str,
                             profit: float, action_log: str = "") -> int:
        """插入每日汇总记录，返回自增ID"""
        cursor = self._conn.execute(
            """INSERT INTO daily_summary (date, strategy_type, profit, action_log)
               VALUES (?, ?, ?, ?)""",
            (date_str, strategy_type, profit, action_log),
        )
        self._conn.commit()
        return cursor.lastrowid

    # ==================== 策略执行日志 ====================

    def insert_execution_log(self, strategy_name: str, status: str,
                             duration_ms: int, error_message: str = "") -> int:
        """插入策略执行日志，返回自增ID"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            """INSERT INTO strategy_execution_log (strategy_name, trigger_time, status, duration_ms, error_message, record_time)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (strategy_name, now, status, duration_ms, error_message[:500], now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_execution_logs(self, strategy_name: str = "", limit: int = 20) -> List[Dict]:
        """查询策略执行日志"""
        if strategy_name:
            cursor = self._conn.execute(
                """SELECT * FROM strategy_execution_log
                   WHERE strategy_name = ?
                   ORDER BY trigger_time DESC LIMIT ?""",
                (strategy_name, limit),
            )
        else:
            cursor = self._conn.execute(
                """SELECT * FROM strategy_execution_log
                   ORDER BY trigger_time DESC LIMIT ?""",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 告警事件 ====================

    def insert_alert_event(self, level: str, source: str, message: str) -> int:
        """插入告警事件，返回自增ID"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            """INSERT INTO alert_event (level, source, message, timestamp)
               VALUES (?, ?, ?, ?)""",
            (level, source, message[:500], now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_alert_events(self, limit: int = 20) -> List[Dict]:
        """查询告警事件，按时间倒序"""
        cursor = self._conn.execute(
            """SELECT * FROM alert_event
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 通知发送记录 ====================

    def insert_notification_log(self, channel: str, event_type: str,
                                title: str, message: str, status: str) -> int:
        """插入通知发送记录，返回自增ID"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            """INSERT INTO notification_log (channel, event_type, title, message, status, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (channel, event_type, title[:200], message[:500], status, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_notification_logs(self, limit: int = 20) -> List[Dict]:
        """查询通知发送记录，按时间倒序"""
        cursor = self._conn.execute(
            """SELECT * FROM notification_log
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 系统状态KV ====================

    def upsert_system_status(self, key: str, value: str) -> None:
        """插入或更新系统状态键值对"""
        self._conn.execute(
            """INSERT INTO system_status (key, value)
               VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value[:500]),
        )
        self._conn.commit()

    def get_system_status(self, key: str) -> Optional[str]:
        """获取系统状态值"""
        cursor = self._conn.execute(
            "SELECT value FROM system_status WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row["value"] if row else None
