"""测试Dashboard Flask API端点"""

import sqlite3
import json
from datetime import datetime, timedelta

import pytest

from data.models import init_db
from data.storage import Storage
from dashboard.app import create_app


@pytest.fixture
def app_client():
    """创建测试用Flask app和client，使用内存DB"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)

    # 初始化一些测试数据
    _seed_test_data(storage)

    app = create_app(storage=storage)
    app.config["TESTING"] = True
    # 将conn也存到app中，以便测试后关闭
    app._test_conn = conn

    with app.test_client() as client:
        yield client

    conn.close()


def _seed_test_data(storage):
    """填充测试数据"""
    # LOF基金
    storage.upsert_lof_fund("164906", "交银互联网", status="normal")
    storage.upsert_lof_fund("501050", "华夏上证50", status="normal")

    # 溢价率历史
    for i in range(25):
        storage.insert_premium_history(
            f"2026-05-01 09:{i:02d}:00",
            "164906" if i % 2 == 0 else "501050",
            1.0 + i * 0.01, 1.0, i * 0.1, "realtime",
        )

    # 交易信号
    storage.insert_trade_signal("2026-05-01 09:30:00", "164906", 3.5, "sell", "pending", "realtime")
    storage.insert_trade_signal("2026-05-01 09:35:00", "501050", 2.8, "buy", "pending", "realtime")

    # 系统状态（使用过去的启动时间，确保uptime为正）
    start_time = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    storage.upsert_system_status("start_time", start_time)
    storage.upsert_system_status("selfcheck_result", "ok")

    # 策略执行日志
    storage.insert_execution_log("lof_premium", "success", 120)
    storage.insert_execution_log("lof_premium", "success", 80)
    storage.insert_execution_log("bond_ipo", "success", 50)

    # 告警事件
    storage.insert_alert_event("INFO", "heartbeat", "心跳正常")
    storage.insert_alert_event("WARN", "data_source", "数据源切换")

    # 通知记录
    storage.insert_notification_log("desktop", "premium_alert", "溢价提醒", "溢价超阈值", "success")
    storage.insert_notification_log("wechat", "ipo_notify", "打新通知", "可转债申购", "fail")

    # 配置项
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "1", "bool", "启用策略", "")
    storage.upsert_config_kv("strategy", "bond_ipo", "max_consecutive_miss", "2", "int", "连续未中暂停", "")
    storage.upsert_config_kv("notify", "desktop", "enabled", "1", "bool", "桌面通知", "")


# ==================== LOF溢价率分页 ====================

def test_api_data_lof_premium_paginated(app_client):
    """验证LOF溢价率API分页响应格式"""
    resp = app_client.get("/api/data/lof_premium?page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.get_json()
    # 验证分页结构
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "total_pages" in data
    assert data["total"] == 25
    assert len(data["items"]) == 10
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["total_pages"] == 3


def test_api_data_lof_premium_search(app_client):
    """验证LOF溢价率API搜索过滤"""
    # 搜索164906
    resp = app_client.get("/api/data/lof_premium?search=164906&page_size=50")
    assert resp.status_code == 200
    data = resp.get_json()
    # 164906对应偶数索引，共13条
    assert data["total"] == 13
    for item in data["items"]:
        assert item["fund_code"] == "164906"

    # 搜索501050
    resp = app_client.get("/api/data/lof_premium?search=501050&page_size=50")
    data = resp.get_json()
    assert data["total"] == 12
    for item in data["items"]:
        assert item["fund_code"] == "501050"


# ==================== 交易信号API ====================

def test_api_data_trade_signal(app_client):
    """验证交易信号API"""
    resp = app_client.get("/api/data/trade_signal")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    # 默认按trigger_time DESC排序
    assert data["items"][0]["fund_code"] == "501050"


# ==================== 状态API分页 ====================

def test_api_status_paginated(app_client):
    """验证状态API的分页参数"""
    resp = app_client.get("/api/status?alert_page=1&alert_page_size=1&notif_page=1&notif_page_size=1")
    assert resp.status_code == 200
    data = resp.get_json()

    # 验证系统状态字段
    assert "system" in data
    assert data["system"]["status"] == "running"
    assert data["system"]["uptime_seconds"] > 0
    assert data["system"]["selfcheck"] == "ok"

    # 验证告警分页
    assert "alert_events" in data
    assert data["alert_events"]["page"] == 1
    assert data["alert_events"]["page_size"] == 1
    assert len(data["alert_events"]["items"]) == 1

    # 验证通知分页
    assert "notification_logs" in data
    assert data["notification_logs"]["page"] == 1
    assert data["notification_logs"]["page_size"] == 1
    assert len(data["notification_logs"]["items"]) == 1

    # 验证其他字段存在
    assert "data_sources" in data
    assert "notifications" in data
    assert "strategy_execution" in data
    assert "execution_trend" in data


# ==================== 配置API ====================

def test_api_config_get(app_client):
    """验证配置查询API - 无ConfigManager时返回503"""
    resp = app_client.get("/api/config")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "ConfigManager未初始化"


def test_api_config_get_with_manager(app_client):
    """验证有ConfigManager时配置查询正常工作"""
    # 使用fake config_manager创建app
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "1", "bool", "启用策略", "")

    class FakeConfigManager:
        def get_config(self, category=None):
            if category is not None:
                return storage.get_config_by_category(category)
            result = []
            for cat in ["strategy", "notify"]:
                result.extend(storage.get_config_by_category(cat))
            return result

        def update_config(self, items):
            storage.batch_update_config(items)

        def reload(self):
            pass

    app = create_app(storage=storage, config_manager=FakeConfigManager())
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 查询所有配置
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert len(data["items"]) >= 1

        # 按分类查询
        resp = client.get("/api/config?category=strategy")
        data = resp.get_json()
        assert data["ok"] is True
        assert all(item["category"] == "strategy" for item in data["items"])

    conn.close()


def test_api_config_update(app_client):
    """验证配置批量更新API"""
    # 使用fake config_manager
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "1", "bool", "启用策略", "")
    storage.upsert_config_kv("strategy", "bond_ipo", "max_consecutive_miss", "2", "int", "连续未中暂停", "")

    class FakeConfigManager:
        def get_config(self, category=None):
            if category is not None:
                return storage.get_config_by_category(category)
            result = []
            for cat in ["strategy", "notify"]:
                result.extend(storage.get_config_by_category(cat))
            return result

        def update_config(self, items):
            storage.batch_update_config(items)
            storage.insert_reload_signal()

        def reload(self):
            pass

    app = create_app(storage=storage, config_manager=FakeConfigManager())
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 批量更新
        resp = client.put("/api/config", json={
            "items": [
                {"category": "strategy", "section": "bond_ipo", "key": "enabled", "value": "0"},
                {"category": "strategy", "section": "bond_ipo", "key": "max_consecutive_miss", "value": "5"},
            ]
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["updated"] == 2

        # 验证值已更新
        item1 = storage.get_config_kv("strategy", "bond_ipo", "enabled")
        assert item1["value"] == "0"
        item2 = storage.get_config_kv("strategy", "bond_ipo", "max_consecutive_miss")
        assert item2["value"] == "5"

    conn.close()


def test_api_config_update_empty_items(app_client):
    """验证空items时返回400"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)

    class FakeConfigManager:
        def get_config(self, category=None):
            return []
        def update_config(self, items):
            pass
        def reload(self):
            pass

    app = create_app(storage=storage, config_manager=FakeConfigManager())
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.put("/api/config", json={"items": []})
        assert resp.status_code == 400

    conn.close()


# ==================== 静默API ====================

def test_api_mute_unmute(app_client):
    """验证静默和解除静默API"""
    # 静默基金
    resp = app_client.post("/api/mute", json={"fund_code": "164906", "days": 7})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "muted_until" in data

    # 查询静默基金
    resp = app_client.get("/api/muted_funds")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["items"][0]["code"] == "164906"

    # 解除静默
    resp = app_client.post("/api/unmute", json={"fund_code": "164906"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True

    # 再次查询应无静默基金
    resp = app_client.get("/api/muted_funds")
    data = resp.get_json()
    assert data["total"] == 0


def test_api_mute_missing_code(app_client):
    """验证静默API缺少fund_code返回400"""
    resp = app_client.post("/api/mute", json={"days": 7})
    assert resp.status_code == 400


def test_api_mute_nonexistent_fund(app_client):
    """验证静默不存在基金返回404"""
    resp = app_client.post("/api/mute", json={"fund_code": "999999"})
    assert resp.status_code == 404


# ==================== 其他业务数据API ====================

def test_api_data_bond_ipo(app_client):
    """验证可转债打新API"""
    resp = app_client.get("/api/data/bond_ipo")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data


def test_api_data_reverse_repo(app_client):
    """验证逆回购API"""
    resp = app_client.get("/api/data/reverse_repo")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data


def test_api_data_daily_summary(app_client):
    """验证每日汇总API"""
    resp = app_client.get("/api/data/daily_summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data
