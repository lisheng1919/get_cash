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


# ==================== 策略执行日志 ====================

def test_insert_and_list_execution_log():
    conn = _create_storage()
    storage = Storage(conn)

    storage.insert_execution_log("lof_premium", "success", 36000)
    storage.insert_execution_log("bond_ipo", "fail", 2000, "timeout")

    logs = storage.list_execution_logs()
    assert len(logs) == 2
    assert logs[0]["strategy_name"] == "bond_ipo"
    assert logs[0]["status"] == "fail"
    assert logs[0]["duration_ms"] == 2000
    assert logs[0]["error_message"] == "timeout"

    filtered = storage.list_execution_logs(strategy_name="lof_premium")
    assert len(filtered) == 1
    assert filtered[0]["strategy_name"] == "lof_premium"
    assert filtered[0]["status"] == "success"
    conn.close()


# ==================== 告警事件 ====================

def test_insert_and_list_alert_event():
    conn = _create_storage()
    storage = Storage(conn)

    storage.insert_alert_event("ERROR", "collector", "lof_list失败")
    storage.insert_alert_event("INFO", "heartbeat", "系统正常")

    events = storage.list_alert_events()
    assert len(events) == 2
    assert events[0]["level"] == "INFO"
    assert events[0]["source"] == "heartbeat"
    assert events[1]["level"] == "ERROR"
    conn.close()


# ==================== 通知发送记录 ====================

def test_insert_and_list_notification_log():
    conn = _create_storage()
    storage = Storage(conn)

    storage.insert_notification_log("desktop", "lof_premium", "信号", "详情", "success")
    storage.insert_notification_log("wechat", "bond_ipo", "打新", "详情", "fail")

    logs = storage.list_notification_logs()
    assert len(logs) == 2
    assert logs[0]["channel"] == "wechat"
    assert logs[0]["status"] == "fail"
    conn.close()


# ==================== 数据源状态扩展 ====================

def test_record_data_source_failure_with_reason():
    conn = _create_storage()
    storage = Storage(conn)

    count = storage.record_data_source_failure("lof_iopv", "timeout")
    assert count == 1

    status = storage.get_data_source_status("lof_iopv")
    assert status["status"] == "failure"
    assert status["consecutive_failures"] == 1
    assert status["failure_reason"] == "timeout"
    assert status["last_failure_time"] != ""
    conn.close()


def test_list_all_data_source_status():
    conn = _create_storage()
    storage = Storage(conn)

    storage.update_data_source_status("lof_list", "ok")
    storage.record_data_source_failure("bond_ipo", "timeout")

    all_status = storage.list_all_data_source_status()
    assert len(all_status) == 2
    conn.close()


# ==================== 系统状态KV ====================

def test_upsert_and_get_system_status():
    conn = _create_storage()
    storage = Storage(conn)

    storage.upsert_system_status("start_time", "2026-04-30 14:00:00")
    assert storage.get_system_status("start_time") == "2026-04-30 14:00:00"

    # 更新
    storage.upsert_system_status("start_time", "2026-04-30 15:00:00")
    assert storage.get_system_status("start_time") == "2026-04-30 15:00:00"

    # 不存在的key
    assert storage.get_system_status("nonexistent") is None
    conn.close()


# ==================== LOF基金静默 ====================

def test_mute_fund():
    """测试设置基金静默"""
    conn = _create_storage()
    storage = Storage(conn)

    # 先插入一个基金
    storage.upsert_lof_fund("164906", "测试LOF", status="normal", is_suspended=False, daily_volume=1000.0)

    # 设置静默
    storage.mute_fund("164906", "2026-05-30 23:59:59", "暂停申购")

    result = storage.get_lof_fund("164906")
    assert result["status"] == "muted"
    assert result["muted_until"] == "2026-05-30 23:59:59"
    assert result["mute_reason"] == "暂停申购"
    conn.close()


def test_unmute_fund():
    """测试解除基金静默"""
    conn = _create_storage()
    storage = Storage(conn)

    storage.upsert_lof_fund("164906", "测试LOF", status="muted", is_suspended=False, daily_volume=1000.0)
    storage.mute_fund("164906", "2026-05-30 23:59:59", "手动静默")

    # 解除静默
    storage.unmute_fund("164906")

    result = storage.get_lof_fund("164906")
    assert result["status"] == "normal"
    assert result["muted_until"] == ""
    assert result["mute_reason"] == ""
    conn.close()


def test_list_muted_funds():
    """测试查询所有静默基金"""
    conn = _create_storage()
    storage = Storage(conn)

    storage.upsert_lof_fund("164906", "LOF-A", status="normal", is_suspended=False, daily_volume=1000.0)
    storage.upsert_lof_fund("501050", "LOF-B", status="normal", is_suspended=False, daily_volume=2000.0)
    storage.upsert_lof_fund("162719", "LOF-C", status="normal", is_suspended=False, daily_volume=3000.0)

    # 只静默两只
    storage.mute_fund("164906", "2026-05-30 23:59:59", "暂停申购")
    storage.mute_fund("501050", "2026-05-01 23:59:59", "套利利润不足(¥32)")

    muted = storage.list_muted_funds()
    assert len(muted) == 2
    codes = [m["code"] for m in muted]
    assert "164906" in codes
    assert "501050" in codes
    assert "162719" not in codes
    conn.close()
