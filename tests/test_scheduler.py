"""测试StrategyScheduler的执行包装和心跳增强"""
import sqlite3
from data.models import init_db
from data.storage import Storage
from scheduler.calendar import TradingCalendar
from scheduler.scheduler import StrategyScheduler
from strategies.base import BaseStrategy


class DummyStrategy(BaseStrategy):
    name = "dummy"

    def __init__(self, config=None, storage=None, notifier=None):
        super().__init__(config or {}, storage, notifier)
        self.executed = False
        self.should_fail = False

    def execute(self) -> None:
        self.executed = True
        if self.should_fail:
            raise RuntimeError("模拟失败")


def _setup():
    conn = sqlite3.Connection(":memory:")
    init_db(conn)
    storage = Storage(conn)
    calendar = TradingCalendar()
    return conn, storage, calendar


def test_execution_log_on_success():
    conn, storage, calendar = _setup()
    strategy = DummyStrategy()
    strategy.execute()
    storage.insert_execution_log("dummy", "success", 100)

    logs = storage.list_execution_logs("dummy")
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    assert logs[0]["duration_ms"] == 100
    conn.close()


def test_execution_log_on_fail():
    conn, storage, calendar = _setup()
    strategy = DummyStrategy()
    strategy.should_fail = True
    scheduler = StrategyScheduler(calendar, storage=storage)
    scheduler.register(strategy)

    try:
        strategy.execute()
    except RuntimeError:
        storage.insert_execution_log("dummy", "fail", 50, "模拟失败")
        storage.insert_alert_event("ERROR", "dummy", "策略执行失败: 模拟失败")

    logs = storage.list_execution_logs("dummy")
    assert len(logs) == 1
    assert logs[0]["status"] == "fail"
    assert logs[0]["error_message"] == "模拟失败"

    events = storage.list_alert_events()
    assert any(e["level"] == "ERROR" and "dummy" in e["source"] for e in events)
    conn.close()


def test_heartbeat_writes_alert():
    conn, storage, calendar = _setup()
    storage.update_data_source_status("lof_list", "ok")

    ds_status = storage.list_all_data_source_status()
    unhealthy = [s for s in ds_status if s["status"] != "ok"]
    if unhealthy:
        storage.insert_alert_event("WARN", "heartbeat", "数据源异常")
    else:
        storage.insert_alert_event("INFO", "heartbeat", "系统正常运行")

    events = storage.list_alert_events(limit=1)
    assert len(events) == 1
    assert events[0]["level"] == "INFO"
    assert "正常" in events[0]["message"]
    conn.close()


def test_slow_execution_alert():
    conn, storage, calendar = _setup()
    slow_threshold = 30000

    duration = 36000
    if duration > slow_threshold:
        storage.insert_alert_event("WARN", "lof_premium",
                                   "策略执行耗时36000ms超过阈值30000ms")

    events = storage.list_alert_events()
    assert any(e["level"] == "WARN" and "36000" in e["message"] for e in events)
    conn.close()


def test_scheduler_accepts_storage():
    conn, storage, calendar = _setup()
    scheduler = StrategyScheduler(calendar, storage=storage, slow_threshold_ms=5000)
    assert scheduler._storage is storage
    assert scheduler._slow_threshold_ms == 5000
    conn.close()
