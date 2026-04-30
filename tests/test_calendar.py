"""交易日历管理测试模块"""

from datetime import date
from scheduler.calendar import TradingCalendar


def test_weekday_is_trading_day():
    cal = TradingCalendar()
    assert cal.is_trading_day(date(2026, 4, 29)) is True  # 周三


def test_weekend_not_trading_day():
    cal = TradingCalendar()
    assert cal.is_trading_day(date(2026, 5, 2)) is False  # 周六
    assert cal.is_trading_day(date(2026, 5, 3)) is False  # 周日


def test_holiday_not_trading_day():
    cal = TradingCalendar()
    cal.add_holiday(date(2026, 5, 1), "劳动节")
    assert cal.is_trading_day(date(2026, 5, 1)) is False


def test_pre_holiday_detection():
    cal = TradingCalendar()
    cal.add_pre_holiday(date(2026, 9, 30), "国庆节前")
    assert cal.is_pre_holiday(date(2026, 9, 30)) is True
    assert cal.is_pre_holiday(date(2026, 9, 29)) is False


def test_next_trading_day():
    cal = TradingCalendar()
    next_day = cal.next_trading_day(date(2026, 5, 1))  # 周五
    assert next_day.weekday() < 5


def test_get_upcoming_pre_holidays():
    cal = TradingCalendar()
    cal.add_pre_holiday(date(2026, 9, 30), "国庆节前")
    cal.add_pre_holiday(date(2027, 1, 29), "春节前")
    results = cal.get_upcoming_pre_holidays(date(2026, 6, 1))
    assert len(results) >= 1


def test_sync_from_akshare_populates_holidays():
    """sync_from_akshare应将交易日和非交易日写入数据库"""
    import sqlite3
    from unittest.mock import patch
    import pandas as pd
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    cal = TradingCalendar()

    fake_trade_dates = [
        "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
        "2026-05-04", "2026-05-05",
    ]

    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_trade_dates})
        cal.sync_from_akshare(storage)

    assert cal.is_trading_day(date(2026, 5, 1)) is False


def test_sync_from_akshare_detects_pre_holiday():
    """sync_from_akshare应检测节前交易日"""
    import sqlite3
    from unittest.mock import patch
    import pandas as pd
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    cal = TradingCalendar()

    fake_trade_dates = [
        "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
        "2026-05-04", "2026-05-05",
    ]

    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_trade_dates})
        cal.sync_from_akshare(storage)

    assert cal.is_pre_holiday(date(2026, 4, 30)) is True


def test_infer_holiday_name():
    """根据月份推断节假日名称"""
    cal = TradingCalendar()
    assert cal._infer_holiday_name(1) == "元旦"
    assert cal._infer_holiday_name(2) == "春节"
    assert cal._infer_holiday_name(4) == "清明节"
    assert cal._infer_holiday_name(5) == "劳动节"
    assert cal._infer_holiday_name(6) == "端午节"
    assert cal._infer_holiday_name(9) == "中秋节"
    assert cal._infer_holiday_name(10) == "国庆节"
    assert cal._infer_holiday_name(3) == "节假日"


def test_sync_incremental():
    """增量同步：已有数据时只拉取新数据"""
    import sqlite3
    from unittest.mock import patch
    import pandas as pd
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    cal = TradingCalendar()

    fake_dates_1 = ["2026-01-02", "2026-01-05"]
    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_dates_1})
        cal.sync_from_akshare(storage)

    fake_dates_2 = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_dates_2})
        cal.sync_from_akshare(storage)

    cursor = storage._conn.execute("SELECT COUNT(*) FROM holiday_calendar")
    count = cursor.fetchone()[0]
    assert count >= 4
