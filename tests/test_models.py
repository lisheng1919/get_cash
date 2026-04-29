"""测试数据库模型初始化：验证init_db创建了所有10张表"""

import sqlite3

from data.models import init_db, TABLE_NAMES


def test_init_db_creates_all_tables():
    """验证init_db后数据库中包含所有10张表"""
    conn = sqlite3.Connection(":memory:")
    init_db(conn)

    # 查询sqlite_master获取所有用户表名
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    actual_tables = {row[0] for row in cursor.fetchall()}

    for table_name in TABLE_NAMES:
        assert table_name in actual_tables, f"表 {table_name} 未被创建"

    # 确认恰好10张表
    assert len(actual_tables) == len(TABLE_NAMES)

    conn.close()


def test_init_db_idempotent():
    """验证init_db可以重复调用不会报错（IF NOT EXISTS）"""
    conn = sqlite3.Connection(":memory:")
    init_db(conn)
    # 再次调用不应抛异常
    init_db(conn)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    actual_tables = {row[0] for row in cursor.fetchall()}
    assert len(actual_tables) == len(TABLE_NAMES)

    conn.close()


def test_init_db_creates_indexes():
    """验证init_db创建了所需的4个索引"""
    conn = sqlite3.Connection(":memory:")
    init_db(conn)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    )
    index_names = {row[0] for row in cursor.fetchall()}

    expected_indexes = {
        "idx_premium_history_code",
        "idx_premium_history_ts",
        "idx_trade_signal_code",
        "idx_holiday_date",
    }

    for idx in expected_indexes:
        assert idx in index_names, f"索引 {idx} 未被创建"

    conn.close()
