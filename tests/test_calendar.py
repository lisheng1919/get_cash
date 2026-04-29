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
