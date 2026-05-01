"""测试Storage的配置CRUD和分页查询方法"""

import sqlite3
import pytest
from data.models import init_db
from data.storage import Storage


def _create_storage():
    conn = sqlite3.Connection(":memory:")
    init_db(conn)
    return conn, Storage(conn)


# ==================== config_kv CRUD ====================

def test_upsert_and_get_config():
    conn, storage = _create_storage()
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "是否启用可转债打新策略")
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result is not None
    assert result["value"] == "true"
    assert result["value_type"] == "bool"
    assert result["label"] == "启用策略"
    conn.close()


def test_get_config_by_category():
    conn, storage = _create_storage()
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "")
    storage.upsert_config_kv("strategy", "lof_premium", "enabled", "true", "bool", "启用策略", "")
    storage.upsert_config_kv("notify", "desktop", "enabled", "true", "bool", "启用桌面通知", "")
    result = storage.get_config_by_category("strategy")
    assert len(result) == 2
    conn.close()


def test_update_config_kv():
    conn, storage = _create_storage()
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "")
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "false", "bool", "启用策略", "")
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result["value"] == "false"
    conn.close()


def test_batch_update_config():
    conn, storage = _create_storage()
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "")
    storage.upsert_config_kv("strategy", "lof_premium", "enabled", "true", "bool", "启用策略", "")
    items = [
        {"category": "strategy", "section": "bond_ipo", "key": "enabled", "value": "false"},
        {"category": "strategy", "section": "lof_premium", "key": "enabled", "value": "false"},
    ]
    storage.batch_update_config(items)
    assert storage.get_config_kv("strategy", "bond_ipo", "enabled")["value"] == "false"
    assert storage.get_config_kv("strategy", "lof_premium", "enabled")["value"] == "false"
    conn.close()


# ==================== 分页查询 ====================

def test_query_premium_history_paginated():
    conn, storage = _create_storage()
    for i in range(25):
        storage.insert_premium_history(
            f"2026-05-01 09:{i:02d}:00", "164906", 1.0 + i * 0.01, 1.0, i * 0.1, "realtime"
        )
    result = storage.query_paginated("premium_history", page=1, page_size=10,
                                      order_by="timestamp", order_dir="DESC")
    assert result["total"] == 25
    assert len(result["items"]) == 10
    assert result["total_pages"] == 3
    conn.close()


def test_query_premium_history_with_search():
    conn, storage = _create_storage()
    storage.insert_premium_history("2026-05-01 09:00:00", "164906", 1.0, 1.0, 0.0, "realtime")
    storage.insert_premium_history("2026-05-01 09:01:00", "501050", 2.0, 2.0, 0.0, "realtime")
    result = storage.query_paginated("premium_history", page=1, page_size=20,
                                      search="164906", search_columns=["fund_code"],
                                      order_by="timestamp", order_dir="DESC")
    assert result["total"] == 1
    assert result["items"][0]["fund_code"] == "164906"
    conn.close()


def test_query_paginated_page2():
    conn, storage = _create_storage()
    for i in range(25):
        storage.insert_premium_history(
            f"2026-05-01 09:{i:02d}:00", "164906", 1.0, 1.0, 0.0, "realtime"
        )
    result = storage.query_paginated("premium_history", page=2, page_size=10,
                                      order_by="timestamp", order_dir="DESC")
    assert len(result["items"]) == 10
    assert result["page"] == 2
    conn.close()


# ==================== 重载信号 ====================

def test_insert_and_get_reload_signal():
    conn, storage = _create_storage()
    storage.insert_reload_signal()
    signals = storage.get_unprocessed_reload_signals()
    assert len(signals) == 1
    assert signals[0]["processed"] == 0
    conn.close()


def test_mark_signal_processed():
    conn, storage = _create_storage()
    storage.insert_reload_signal()
    signals = storage.get_unprocessed_reload_signals()
    storage.mark_reload_signal_processed(signals[0]["id"])
    signals2 = storage.get_unprocessed_reload_signals()
    assert len(signals2) == 0
    conn.close()


# ==================== 白名单校验 ====================

def test_query_paginated_rejects_invalid_order_dir():
    """order_dir仅允许ASC/DESC，其他值应抛出ValueError"""
    conn, storage = _create_storage()
    with pytest.raises(ValueError, match="order_dir"):
        storage.query_paginated("premium_history", order_dir="INVALID")
    conn.close()


def test_query_paginated_rejects_invalid_table_name():
    """table名仅允许合法SQL标识符"""
    conn, storage = _create_storage()
    with pytest.raises(ValueError, match="table"):
        storage.query_paginated("premium_history; DROP TABLE--")
    conn.close()


def test_query_paginated_rejects_invalid_column_name():
    """search_columns仅允许合法SQL标识符"""
    conn, storage = _create_storage()
    with pytest.raises(ValueError, match="column"):
        storage.query_paginated("premium_history", search="test",
                                search_columns=["fund_code; DROP TABLE--"])
    conn.close()


def test_query_paginated_rejects_invalid_order_by():
    """order_by仅允许合法SQL标识符"""
    conn, storage = _create_storage()
    with pytest.raises(ValueError, match="order_by"):
        storage.query_paginated("premium_history", order_by="id; DROP TABLE--")
    conn.close()


def test_query_paginated_accepts_valid_params():
    """合法参数应正常工作"""
    conn, storage = _create_storage()
    storage.insert_premium_history("2026-05-01 09:00:00", "164906", 1.0, 1.0, 0.0, "realtime")
    result = storage.query_paginated("premium_history", order_by="timestamp", order_dir="ASC",
                                      search="164906", search_columns=["fund_code"])
    assert result["total"] == 1
    conn.close()


# ==================== premium_hourly 聚合 ====================

def test_upsert_premium_hourly():
    conn, storage = _create_storage()
    storage.upsert_premium_hourly("164906", "2026-05-01 09", 3.0, 4.0, 2.0, 1.0, 1.0, 10, 2)
    row = storage._conn.execute(
        "SELECT * FROM premium_hourly WHERE fund_code='164906' AND hour='2026-05-01 09'"
    ).fetchone()
    assert row is not None
    assert row["avg_premium"] == 3.0
    assert row["sample_count"] == 10
    conn.close()


def test_upsert_premium_hourly_updates_existing():
    conn, storage = _create_storage()
    storage.upsert_premium_hourly("164906", "2026-05-01 09", 3.0, 4.0, 2.0, 1.0, 1.0, 10, 2)
    storage.upsert_premium_hourly("164906", "2026-05-01 09", 3.5, 5.0, 2.0, 1.1, 1.0, 15, 3)
    row = storage._conn.execute(
        "SELECT * FROM premium_hourly WHERE fund_code='164906' AND hour='2026-05-01 09'"
    ).fetchone()
    assert row["avg_premium"] == 3.5
    assert row["sample_count"] == 15
    conn.close()


def test_aggregate_premium_hourly():
    """验证聚合逻辑：聚合指定小时的数据到premium_hourly"""
    conn, storage = _create_storage()
    for i in range(3):
        storage.insert_premium_history(
            f"2026-05-01 09:{i*20:02d}:00", "164906",
            1.0 + i * 0.01, 1.0, 2.0 + i, "estimated"
        )
    storage.insert_premium_history(
        "2026-05-01 10:00:00", "164906", 1.0, 1.0, 3.0, "estimated"
    )

    count = storage.aggregate_premium_hourly("2026-05-01 09", threshold=3.0)
    assert count == 1

    row = storage._conn.execute(
        "SELECT * FROM premium_hourly WHERE fund_code='164906' AND hour='2026-05-01 09'"
    ).fetchone()
    assert row is not None
    assert row["sample_count"] == 3
    assert row["avg_premium"] == 3.0
    assert row["max_premium"] == 4.0
    assert row["min_premium"] == 2.0
    assert row["threshold_count"] == 2

    remaining = storage._conn.execute(
        "SELECT COUNT(*) as cnt FROM premium_history WHERE fund_code='164906' AND timestamp LIKE '2026-05-01 09%'"
    ).fetchone()["cnt"]
    # premium_rate 2.0 < 3.0 被删除, 3.0和4.0 >= 3.0 保留
    assert remaining == 2
    conn.close()


def test_aggregate_premium_hourly_no_data():
    """无数据时不聚合"""
    conn, storage = _create_storage()
    count = storage.aggregate_premium_hourly("2026-05-01 09", threshold=3.0)
    assert count == 0
    conn.close()


def test_cleanup_old_premium_data():
    """验证数据清理：删除超过保留期的记录"""
    conn, storage = _create_storage()
    storage.insert_premium_history(
        "2026-01-01 09:00:00", "164906", 1.0, 1.0, 3.0, "estimated"
    )
    storage.upsert_premium_hourly("164906", "2026-01-01 09", 3.0, 3.0, 3.0, 1.0, 1.0, 1, 1)

    deleted = storage.cleanup_old_premium_data(retention_days=90, now_str="2026-05-01 00:00:00")
    assert deleted >= 1

    cnt = storage._conn.execute(
        "SELECT COUNT(*) as cnt FROM premium_history WHERE fund_code='164906'"
    ).fetchone()["cnt"]
    assert cnt == 0
    cnt2 = storage._conn.execute(
        "SELECT COUNT(*) as cnt FROM premium_hourly WHERE fund_code='164906'"
    ).fetchone()["cnt"]
    assert cnt2 == 0
    conn.close()


def test_get_premium_hourly_summary():
    """验证获取基金分组汇总"""
    conn, storage = _create_storage()
    storage.upsert_premium_hourly("164906", "2026-05-01 09", 3.0, 4.0, 2.0, 1.0, 1.0, 10, 2)
    storage.upsert_premium_hourly("501050", "2026-05-01 09", 1.5, 2.0, 1.0, 2.0, 2.0, 8, 0)

    result = storage.query_paginated("premium_hourly", page=1, page_size=10,
                                      order_by="fund_code", order_dir="ASC")
    assert result["total"] == 2
    conn.close()


def test_get_premium_hourly_by_fund():
    """验证获取指定基金的小时汇总"""
    conn, storage = _create_storage()
    storage.upsert_premium_hourly("164906", "2026-05-01 09", 3.0, 4.0, 2.0, 1.0, 1.0, 10, 2)
    storage.upsert_premium_hourly("164906", "2026-05-01 10", 3.5, 5.0, 2.5, 1.1, 1.0, 12, 3)
    storage.upsert_premium_hourly("501050", "2026-05-01 09", 1.5, 2.0, 1.0, 2.0, 2.0, 8, 0)

    result = storage.query_paginated("premium_hourly", page=1, page_size=10,
                                      extra_where="fund_code='164906'",
                                      order_by="hour", order_dir="DESC")
    assert result["total"] == 2
    conn.close()
