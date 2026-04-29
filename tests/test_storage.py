"""测试Storage类的各项数据操作方法"""

import sqlite3

from data.models import init_db
from data.storage import Storage


def _create_storage() -> sqlite3.Connection:
    """创建内存数据库并初始化，返回连接"""
    conn = sqlite3.Connection(":memory:")
    init_db(conn)
    return conn


# ==================== LOF基金 ====================

def test_upsert_and_get_lof_fund():
    """测试LOF基金的插入和查询"""
    conn = _create_storage()
    storage = Storage(conn)

    # 插入
    storage.upsert_lof_fund("164906", "交银中证海外中国互联网", status="normal",
                            is_suspended=False, daily_volume=5000000.0)

    result = storage.get_lof_fund("164906")
    assert result is not None
    assert result["code"] == "164906"
    assert result["name"] == "交银中证海外中国互联网"
    assert result["status"] == "normal"
    assert result["is_suspended"] == 0
    assert result["daily_volume"] == 5000000.0

    # 更新（upsert）
    storage.upsert_lof_fund("164906", "交银中证海外中国互联网(更新)",
                            status="suspended", is_suspended=True, daily_volume=3000000.0)

    result = storage.get_lof_fund("164906")
    assert result is not None
    assert result["name"] == "交银中证海外中国互联网(更新)"
    assert result["status"] == "suspended"
    assert result["is_suspended"] == 1

    # 查询不存在的基金
    assert storage.get_lof_fund("999999") is None

    conn.close()


# ==================== 溢价率历史 ====================

def test_insert_and_get_premium_history():
    """测试溢价率历史的插入和查询"""
    conn = _create_storage()
    storage = Storage(conn)

    # 插入多条记录
    storage.insert_premium_history("2026-04-29 10:00:00", "164906",
                                   1.234, 1.300, -5.08, "eastmoney")
    storage.insert_premium_history("2026-04-29 14:00:00", "164906",
                                   1.250, 1.310, -4.58, "eastmoney")
    storage.insert_premium_history("2026-04-29 10:00:00", "501050",
                                   0.800, 0.820, -2.44, "eastmoney")

    # 查询164906的溢价率历史
    results = storage.get_premium_history("164906")
    assert len(results) == 2
    # 按时间倒序，最新在前
    assert results[0]["timestamp"] == "2026-04-29 14:00:00"
    assert results[0]["premium_rate"] == -4.58
    assert results[1]["premium_rate"] == -5.08

    # 查询不存在的基金
    results = storage.get_premium_history("999999")
    assert len(results) == 0

    conn.close()


# ==================== 交易信号 ====================

def test_insert_and_get_trade_signals():
    """测试交易信号的插入和查询"""
    conn = _create_storage()
    storage = Storage(conn)

    # 插入信号
    signal_id = storage.insert_trade_signal("2026-04-29 10:30:00", "164906",
                                            -5.0, "buy", status="pending")
    assert signal_id > 0

    storage.insert_trade_signal("2026-04-29 11:00:00", "164906",
                                -3.0, "sell", status="executed")
    storage.insert_trade_signal("2026-04-29 10:00:00", "501050",
                                -2.0, "buy", status="pending")

    # 按基金代码查询
    results = storage.get_trade_signals(fund_code="164906")
    assert len(results) == 2
    assert results[0]["action"] == "sell"
    assert results[1]["action"] == "buy"

    # 查询全部信号
    results = storage.get_trade_signals()
    assert len(results) == 3

    conn.close()


# ==================== 节假日日历 ====================

def test_upsert_holiday_and_is_pre_holiday():
    """测试节假日日历的插入和节前判断"""
    conn = _create_storage()
    storage = Storage(conn)

    # 插入节前交易日
    storage.upsert_holiday("2026-09-30", is_trading_day=True,
                           is_pre_holiday=True, holiday_name="国庆节前")
    # 插入普通交易日
    storage.upsert_holiday("2026-04-29", is_trading_day=True,
                           is_pre_holiday=False, holiday_name="")

    # 节前判断
    assert storage.is_pre_holiday("2026-09-30") is True
    assert storage.is_pre_holiday("2026-04-29") is False

    # 无记录时返回False
    assert storage.is_pre_holiday("2026-05-01") is False

    conn.close()


def test_is_trading_day_weekend():
    """测试周末判断：周六和周日不是交易日"""
    conn = _create_storage()
    storage = Storage(conn)

    # 2026-04-25是周六，2026-04-26是周日
    assert storage.is_trading_day("2026-04-25") is False
    assert storage.is_trading_day("2026-04-26") is False

    # 2026-04-27是周一，无记录时应为交易日
    assert storage.is_trading_day("2026-04-27") is True

    # 插入节假日记录覆盖周末判断
    storage.upsert_holiday("2026-04-27", is_trading_day=False,
                           is_pre_holiday=False, holiday_name="补休")
    assert storage.is_trading_day("2026-04-27") is False

    conn.close()


# ==================== 数据源状态 ====================

def test_update_and_get_data_source_status():
    """测试数据源状态的更新和查询"""
    conn = _create_storage()
    storage = Storage(conn)

    # 初始状态不存在
    assert storage.get_data_source_status("eastmoney") is None

    # 更新为成功状态
    storage.update_data_source_status("eastmoney", "success")
    result = storage.get_data_source_status("eastmoney")
    assert result is not None
    assert result["name"] == "eastmoney"
    assert result["status"] == "success"
    assert result["consecutive_failures"] == 0

    conn.close()


def test_record_data_source_failure():
    """测试数据源失败记录"""
    conn = _create_storage()
    storage = Storage(conn)

    # 记录失败（数据源不存在时自动创建）
    count = storage.record_data_source_failure("eastmoney")
    assert count == 1

    result = storage.get_data_source_status("eastmoney")
    assert result["status"] == "failure"
    assert result["consecutive_failures"] == 1

    # 再次记录失败
    count = storage.record_data_source_failure("eastmoney")
    assert count == 2

    # 成功后重置失败计数
    storage.update_data_source_status("eastmoney", "success")
    result = storage.get_data_source_status("eastmoney")
    assert result["consecutive_failures"] == 0

    conn.close()
