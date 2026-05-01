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
