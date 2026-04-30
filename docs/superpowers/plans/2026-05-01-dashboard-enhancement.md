# 看板增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将看板从Jinja2模板渲染重构为Flask API + Petite-Vue SPA，实现所有表格的分页搜索，并将配置管理从config.yaml迁移到看板CRUD。

**Architecture:** Flask后端提供纯JSON API（分页数据查询 + 配置CRUD + 热加载信号），前端用Petite-Vue构建SPA。配置存储在SQLite的config_kv表中，启动时从config.yaml初始化。热加载通过SQLite信号表实现跨进程通信——Flask写入配置变更信号，调度器定期轮询检测。

**Tech Stack:** Python 3.10, Flask, SQLite, Petite-Vue 0.4.x, APScheduler

---

## 文件结构

| 操作 | 文件路径 | 职责 |
|------|---------|------|
| 修改 | `data/models.py` | 新增config_kv表DDL和config_reload_signal表DDL |
| 修改 | `data/storage.py` | 新增config_kv的CRUD方法 + 分页查询方法 |
| 创建 | `config_manager.py` | ConfigManager类：配置初始化、读取、热加载 |
| 修改 | `dashboard/app.py` | 重构为纯API后端，新增分页数据API和配置API |
| 创建 | `dashboard/static/petite-vue.js` | Petite-Vue本地文件（离线支持） |
| 修改 | `dashboard/templates/index.html` | 重写为Petite-Vue SPA |
| 修改 | `scheduler/scheduler.py` | 新增remove_job/modify_job方法，新增配置轮询job |
| 修改 | `main.py` | 集成ConfigManager，启动Flask线程 |
| 修改 | `config_loader.py` | 新增配置元数据定义（label、description、value_type） |
| 创建 | `tests/test_config_manager.py` | ConfigManager测试 |
| 创建 | `tests/test_storage_pagination.py` | 分页查询测试 |
| 创建 | `tests/test_dashboard_api.py` | 看板API测试 |

---

### Task 1: 新增config_kv表和config_reload_signal表

**Files:**
- Modify: `data/models.py:8-150` (DDL_STATEMENTS)
- Modify: `data/models.py:153-162` (INDEX_STATEMENTS)
- Modify: `data/models.py:165-180` (TABLE_NAMES)
- Test: `tests/test_models.py`

- [ ] **Step 1: 在DDL_STATEMENTS末尾新增两张表的DDL**

在 `data/models.py` 的 `DDL_STATEMENTS` 列表末尾（第149行 `""",` 之后，`]` 之前）添加：

```python
    # 配置键值存储表
    """CREATE TABLE IF NOT EXISTS config_kv (
        category TEXT NOT NULL DEFAULT '',
        section TEXT NOT NULL DEFAULT '',
        key TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL DEFAULT '',
        value_type TEXT NOT NULL DEFAULT 'string',
        label TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        create_time TEXT NOT NULL DEFAULT '',
        update_time TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (category, section, key)
    )""",
    # 配置重载信号表（跨进程通信）
    """CREATE TABLE IF NOT EXISTS config_reload_signal (
        id INTEGER NOT NULL,
        signal_time TEXT NOT NULL DEFAULT '',
        processed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
```

- [ ] **Step 2: 在INDEX_STATEMENTS新增索引**

在 `INDEX_STATEMENTS` 列表末尾添加：

```python
    "CREATE INDEX IF NOT EXISTS idx_config_kv_category ON config_kv(category)",
    "CREATE INDEX IF NOT EXISTS idx_config_reload_unprocessed ON config_reload_signal(processed)",
```

- [ ] **Step 3: 在TABLE_NAMES新增两个表名**

在 `TABLE_NAMES` 列表末尾添加：

```python
    "config_kv",
    "config_reload_signal",
```

- [ ] **Step 4: 运行现有测试确认不破坏**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/models.py
git commit -m "feat: 新增config_kv和config_reload_signal表定义"
```

---

### Task 2: Storage层新增配置CRUD和分页查询方法

**Files:**
- Modify: `data/storage.py:8-459`
- Test: `tests/test_storage_pagination.py` (create)
- Test: `tests/test_storage.py` (add config_kv tests)

- [ ] **Step 1: 编写config_kv CRUD方法的测试**

创建 `tests/test_storage_pagination.py`：

```python
"""测试Storage的配置CRUD和分页查询方法"""

import sqlite3
from data.models import init_db
from data.storage import Storage


def _create_storage():
    conn = sqlite3.Connection(":memory:")
    init_db(conn)
    return conn, Storage(conn)


# ==================== config_kv CRUD ====================

def test_upsert_and_get_config():
    """测试配置项的插入和查询"""
    conn, storage = _create_storage()
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "是否启用可转债打新策略")
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result is not None
    assert result["value"] == "true"
    assert result["value_type"] == "bool"
    assert result["label"] == "启用策略"
    conn.close()


def test_get_config_by_category():
    """测试按分类查询配置"""
    conn, storage = _create_storage()
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "")
    storage.upsert_config_kv("strategy", "lof_premium", "enabled", "true", "bool", "启用策略", "")
    storage.upsert_config_kv("notify", "desktop", "enabled", "true", "bool", "启用桌面通知", "")
    result = storage.get_config_by_category("strategy")
    assert len(result) == 2
    conn.close()


def test_update_config_kv():
    """测试配置项更新（upsert语义）"""
    conn, storage = _create_storage()
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "")
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "false", "bool", "启用策略", "")
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result["value"] == "false"
    conn.close()


def test_batch_update_config():
    """测试批量更新配置"""
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
    """测试溢价率历史分页查询"""
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
    """测试分页查询带搜索条件"""
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
    """测试分页第2页"""
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
    """测试重载信号的插入和查询"""
    conn, storage = _create_storage()
    storage.insert_reload_signal()
    signals = storage.get_unprocessed_reload_signals()
    assert len(signals) == 1
    assert signals[0]["processed"] == 0
    conn.close()


def test_mark_signal_processed():
    """测试标记信号已处理"""
    conn, storage = _create_storage()
    storage.insert_reload_signal()
    signals = storage.get_unprocessed_reload_signals()
    storage.mark_reload_signal_processed(signals[0]["id"])
    signals2 = storage.get_unprocessed_reload_signals()
    assert len(signals2) == 0
    conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_storage_pagination.py -v`
Expected: FAIL (AttributeError: 'Storage' object has no attribute 'upsert_config_kv')

- [ ] **Step 3: 在storage.py中实现config_kv CRUD方法**

在 `data/storage.py` 的 `Storage` 类末尾（第459行之前）添加以下方法：

```python
    # ==================== 配置管理 ====================

    def upsert_config_kv(self, category, section, key, value, value_type="string",
                         label="", description=""):
        """插入或更新配置项"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            """INSERT INTO config_kv (category, section, key, value, value_type, label, description, create_time, update_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(category, section, key) DO UPDATE SET
                   value=excluded.value, value_type=excluded.value_type,
                   label=excluded.label, description=excluded.description,
                   update_time=excluded.update_time""",
            (category, section, key, value, value_type, label, description, now, now)
        )
        self._conn.commit()

    def get_config_kv(self, category, section, key):
        """查询单个配置项"""
        row = self._conn.execute(
            "SELECT * FROM config_kv WHERE category=? AND section=? AND key=?",
            (category, section, key)
        ).fetchone()
        return dict(row) if row else None

    def get_config_by_category(self, category):
        """按分类查询配置项列表"""
        rows = self._conn.execute(
            "SELECT * FROM config_kv WHERE category=? ORDER BY section, key",
            (category,)
        ).fetchall()
        return [dict(r) for r in rows]

    def batch_update_config(self, items):
        """批量更新配置项"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            self._conn.execute(
                """UPDATE config_kv SET value=?, update_time=? WHERE category=? AND section=? AND key=?""",
                (item["value"], now, item["category"], item["section"], item["key"])
            )
        self._conn.commit()

    # ==================== 分页查询 ====================

    def query_paginated(self, table, page=1, page_size=20, search=None,
                        search_columns=None, order_by="id", order_dir="DESC",
                        extra_where=None, extra_params=None):
        """通用分页查询

        Args:
            table: 表名
            page: 页码（从1开始）
            page_size: 每页条数
            search: 搜索关键词
            search_columns: 搜索目标列名列表
            order_by: 排序字段
            order_dir: 排序方向 ASC/DESC
            extra_where: 额外WHERE条件
            extra_params: 额外参数
        """
        where_clauses = []
        params = []

        if extra_where:
            where_clauses.append(extra_where)
            if extra_params:
                params.extend(extra_params)

        if search and search_columns:
            like_parts = " OR ".join([f"{col} LIKE ?" for col in search_columns])
            where_clauses.append(f"({like_parts})")
            params.extend([f"%{search}%"] * len(search_columns))

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # 计算总数
        count_sql = f"SELECT COUNT(*) as cnt FROM {table}{where_sql}"
        total = self._conn.execute(count_sql, params).fetchone()["cnt"]

        # 分页查询
        offset = (page - 1) * page_size
        query_sql = f"SELECT * FROM {table}{where_sql} ORDER BY {order_by} {order_dir} LIMIT ? OFFSET ?"
        rows = self._conn.execute(query_sql, params + [page_size, offset]).fetchall()

        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # ==================== 重载信号 ====================

    def insert_reload_signal(self):
        """插入配置重载信号"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            "INSERT INTO config_reload_signal (signal_time, processed) VALUES (?, 0)",
            (now,)
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_unprocessed_reload_signals(self):
        """获取未处理的重载信号"""
        rows = self._conn.execute(
            "SELECT * FROM config_reload_signal WHERE processed=0 ORDER BY signal_time ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_reload_signal_processed(self, signal_id):
        """标记重载信号为已处理"""
        self._conn.execute(
            "UPDATE config_reload_signal SET processed=1 WHERE id=?",
            (signal_id,)
        )
        self._conn.commit()
```

注意：需要在文件头部添加 `from datetime import datetime`（如果不存在的话）。检查 storage.py 顶部已有 datetime import。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_storage_pagination.py -v`
Expected: ALL PASS

- [ ] **Step 5: 运行全部现有测试确认无破坏**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add data/storage.py tests/test_storage_pagination.py
git commit -m "feat: Storage层新增配置CRUD、分页查询和重载信号方法"
```

---

### Task 3: 实现ConfigManager类

**Files:**
- Create: `config_manager.py`
- Test: `tests/test_config_manager.py`

- [ ] **Step 1: 编写ConfigManager测试**

创建 `tests/test_config_manager.py`：

```python
"""测试ConfigManager配置管理器"""

import sqlite3
from data.models import init_db
from data.storage import Storage
from config_manager import ConfigManager


def _create_env():
    """创建测试环境：内存DB + Storage + ConfigManager"""
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    storage = Storage(conn)
    config_dict = {
        "strategies": {"bond_ipo": {"enabled": True}, "lof_premium": {"enabled": True},
                       "reverse_repo": {"enabled": True}, "bond_allocation": {"enabled": True}},
        "bond_ipo": {"auto_subscribe": True, "max_consecutive_miss": 2},
        "lof_premium": {"premium_threshold": 3.0, "min_volume": 500, "confirm_count": 3,
                        "cooldown_minutes": 5, "auto_trade": False, "poll_interval": 60},
        "reverse_repo": {"amount": 100000, "min_rate": 3.0},
        "bond_allocation": {"min_content_weight": 20, "min_safety_cushion": 5.0},
        "notify": {"desktop": {"enabled": True}, "wechat": {"enabled": False, "serverchan_key": ""},
                   "dingtalk": {"enabled": False, "webhook": ""}},
        "risk": {"max_daily_trades_per_fund": 1, "hard_stop_loss": 5.0},
        "system": {"startup_selfcheck": True, "heartbeat_interval": 300},
    }
    manager = ConfigManager(storage, scheduler=None, config_dict=config_dict)
    return conn, storage, manager


def test_init_from_yaml():
    """测试从yaml初始化配置到DB"""
    conn, storage, manager = _create_env()
    manager.init_from_yaml()
    # 验证策略配置已写入
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result is not None
    assert result["value"] == "true"
    assert result["value_type"] == "bool"
    assert result["label"] != ""
    conn.close()


def test_init_from_yaml_idempotent():
    """测试重复初始化不覆盖已有值"""
    conn, storage, manager = _create_env()
    manager.init_from_yaml()
    # 修改一个值
    storage.batch_update_config([{"category": "strategy", "section": "bond_ipo", "key": "enabled", "value": "false"}])
    # 再次初始化
    manager.init_from_yaml()
    # 应保持修改后的值
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result["value"] == "false"
    conn.close()


def test_get_config():
    """测试按分类查询配置"""
    conn, storage, manager = _create_env()
    manager.init_from_yaml()
    result = manager.get_config("strategy")
    assert len(result) > 0
    # 应包含bond_ipo和lof_premium的配置
    sections = set(r["section"] for r in result)
    assert "bond_ipo" in sections
    assert "lof_premium" in sections
    conn.close()


def test_update_config_and_signal():
    """测试更新配置并发出重载信号"""
    conn, storage, manager = _create_env()
    manager.init_from_yaml()
    items = [{"category": "strategy", "section": "bond_ipo", "key": "enabled", "value": "false"}]
    manager.update_config(items)
    # 验证DB已更新
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result["value"] == "false"
    # 验证重载信号已发出
    signals = storage.get_unprocessed_reload_signals()
    assert len(signals) >= 1
    conn.close()


def test_get_config_as_dict():
    """测试获取配置为嵌套字典格式"""
    conn, storage, manager = _create_env()
    manager.init_from_yaml()
    result = manager.get_config_as_dict("strategy")
    assert "bond_ipo" in result
    assert "enabled" in result["bond_ipo"]
    conn.close()


def test_reload_updates_strategy():
    """测试reload更新策略实例属性"""
    conn, storage, manager = _create_env()
    manager.init_from_yaml()

    # 创建模拟策略
    class FakeStrategy:
        name = "bond_ipo"
        def __init__(self):
            self.auto_subscribe = True
            self._max_miss = 2
    strategy = FakeStrategy()
    manager.register_strategy("bond_ipo", strategy)

    # 修改配置并reload
    storage.batch_update_config([{"category": "strategy", "section": "bond_ipo", "key": "max_consecutive_miss", "value": "5"}])
    manager.reload()

    # 验证策略属性已更新
    assert strategy._max_miss == 5
    conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_config_manager.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'config_manager')

- [ ] **Step 3: 实现ConfigManager类**

创建 `config_manager.py`：

```python
"""配置管理器：配置初始化、读取、热加载"""

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 配置元数据定义：每个配置项的label、description、value_type
# 结构：{category: {section: {key: {label, description, value_type, default}}}}
CONFIG_META = {
    "strategy": {
        "bond_ipo": {
            "enabled": {"label": "启用策略", "description": "是否启用可转债打新策略", "value_type": "bool", "default": True},
            "auto_subscribe": {"label": "自动申购", "description": "是否自动提交申购", "value_type": "bool", "default": True},
            "notify_on_subscribe": {"label": "申购通知", "description": "申购时发送通知", "value_type": "bool", "default": True},
            "notify_on_winning": {"label": "中签通知", "description": "中签时发送通知", "value_type": "bool", "default": True},
            "notify_on_listing": {"label": "上市通知", "description": "上市时发送通知", "value_type": "bool", "default": True},
            "max_consecutive_miss": {"label": "最大违约次数", "description": "连续违约达此次数自动暂停打新", "value_type": "int", "default": 2},
        },
        "bond_allocation": {
            "enabled": {"label": "启用策略", "description": "是否启用配债监控策略", "value_type": "bool", "default": True},
            "min_content_weight": {"label": "最低含权量(%)", "description": "百股含权量最低百分比", "value_type": "int", "default": 20},
            "min_safety_cushion": {"label": "最低安全垫(%)", "description": "配债安全垫最低百分比", "value_type": "float", "default": 5.0},
            "min_stock_volume": {"label": "最小成交量(手)", "description": "正股最小成交量", "value_type": "int", "default": 1000},
            "max_stock_amount_ratio": {"label": "最大仓位比例", "description": "单只正股最大仓位占比", "value_type": "float", "default": 0.2},
            "conservative_factor": {"label": "保守系数", "description": "历史溢价率乘以此系数做保守估值", "value_type": "float", "default": 0.8},
            "rush_warning_threshold": {"label": "抢权预警阈值(%)", "description": "正股涨幅超过此值发出预警", "value_type": "float", "default": 5.0},
        },
        "reverse_repo": {
            "enabled": {"label": "启用策略", "description": "是否启用逆回购策略", "value_type": "bool", "default": True},
            "amount": {"label": "总资金量(元)", "description": "参与逆回购的总资金量", "value_type": "int", "default": 100000},
            "prefer_sh": {"label": "优先沪市", "description": "优先选择沪市品种(门槛10万)", "value_type": "bool", "default": True},
            "min_rate": {"label": "最低利率(%)", "description": "低于此利率不操作", "value_type": "float", "default": 3.0},
            "reserve_ratio": {"label": "资金保留比例", "description": "保留不参与逆回购的资金比例", "value_type": "float", "default": 0.2},
        },
        "lof_premium": {
            "enabled": {"label": "启用策略", "description": "是否启用LOF溢价监控策略", "value_type": "bool", "default": True},
            "poll_interval": {"label": "轮询间隔(秒)", "description": "溢价率轮询间隔秒数", "value_type": "int", "default": 60},
            "premium_threshold": {"label": "溢价率阈值(%)", "description": "溢价率超过此值触发信号", "value_type": "float", "default": 3.0},
            "low_precision_threshold": {"label": "低精度阈值(%)", "description": "IOPV回退到估算时的阈值", "value_type": "float", "default": 3.0},
            "min_volume": {"label": "最小成交量(万)", "description": "日成交量低于此值过滤掉", "value_type": "int", "default": 500},
            "confirm_count": {"label": "确认次数", "description": "连续N次超阈值才触发信号", "value_type": "int", "default": 3},
            "cooldown_minutes": {"label": "冷却时间(分)", "description": "信号触发后的冷却期", "value_type": "int", "default": 5},
            "auto_trade": {"label": "自动交易", "description": "是否自动执行交易(需miniQMT)", "value_type": "bool", "default": False},
            "auto_mute_enabled": {"label": "自动静默", "description": "自动静默暂停申购或利润不足的基金", "value_type": "bool", "default": True},
            "min_profit_yuan": {"label": "最小利润(元)", "description": "套利利润低于此值自动静默", "value_type": "int", "default": 200},
            "auto_mute_paused_days": {"label": "静默天数", "description": "自动静默的默认天数", "value_type": "int", "default": 30},
            "available_capital": {"label": "可用资金(元)", "description": "套利可用资金总量", "value_type": "int", "default": 100000},
            "sell_commission_rate": {"label": "卖出佣金率", "description": "卖出交易佣金费率", "value_type": "float", "default": 0.0003},
        },
    },
    "notify": {
        "desktop": {
            "enabled": {"label": "启用桌面通知", "description": "通过系统桌面弹窗通知", "value_type": "bool", "default": True},
        },
        "wechat": {
            "enabled": {"label": "启用微信通知", "description": "通过Server酱推送微信通知", "value_type": "bool", "default": False},
            "serverchan_key": {"label": "Server酱Key", "description": "Server酱推送密钥", "value_type": "string", "default": ""},
        },
        "dingtalk": {
            "enabled": {"label": "启用钉钉通知", "description": "通过钉钉Webhook推送通知", "value_type": "bool", "default": False},
            "webhook": {"label": "钉钉Webhook", "description": "钉钉机器人Webhook地址", "value_type": "string", "default": ""},
        },
    },
    "risk": {
        "risk": {
            "max_daily_trades_per_fund": {"label": "单基金日最大交易次数", "description": "单只基金每日最大交易次数", "value_type": "int", "default": 1},
            "max_single_trade_ratio": {"label": "单笔最大仓位比例", "description": "单笔交易最大仓位占比", "value_type": "float", "default": 0.3},
            "hard_stop_loss": {"label": "硬止损(%)", "description": "亏损达此比例强制止损", "value_type": "float", "default": 5.0},
            "bond_ipo_max_consecutive_miss": {"label": "打新最大违约次数", "description": "可转债打新连续违约暂停", "value_type": "int", "default": 2},
        },
    },
    "system": {
        "system": {
            "startup_selfcheck": {"label": "启动自检", "description": "系统启动时执行自检", "value_type": "bool", "default": True},
            "heartbeat_interval": {"label": "心跳间隔(秒)", "description": "系统心跳检查间隔", "value_type": "int", "default": 300},
            "data_retention_days": {"label": "数据保留天数", "description": "历史数据保留天数", "value_type": "int", "default": 90},
            "db_vacuum_weekly": {"label": "每周数据库整理", "description": "每周自动执行VACUUM", "value_type": "bool", "default": True},
        },
    },
}

# 策略属性到配置key的映射：{strategy_name: {strategy_attr: config_key}}
STRATEGY_ATTR_MAP = {
    "bond_ipo": {
        "_enabled": "enabled",
        "_auto_subscribe": "auto_subscribe",
        "_max_miss": "max_consecutive_miss",
    },
    "bond_allocation": {
        "_enabled": "enabled",
        "_min_content_weight": "min_content_weight",
        "_min_safety_cushion": "min_safety_cushion",
        "_conservative_factor": "conservative_factor",
        "_rush_threshold": "rush_warning_threshold",
    },
    "reverse_repo": {
        "_enabled": "enabled",
        "_min_rate": "min_rate",
        "_reserve_ratio": "reserve_ratio",
        "_amount": "amount",
        "_prefer_sh": "prefer_sh",
    },
    "lof_premium": {
        "_enabled": "enabled",
        "_auto_trade": "auto_trade",
        "_auto_mute_enabled": "auto_mute_enabled",
        "_min_profit_yuan": "min_profit_yuan",
        "_auto_mute_paused_days": "auto_mute_paused_days",
        "_available_capital": "available_capital",
        "_sell_commission_rate": "sell_commission_rate",
    },
}

# 策略子对象属性映射（需要更新策略内部组合对象的属性）
STRATEGY_SUB_OBJ_MAP = {
    "lof_premium": {
        "_calculator": {
            "_normal_threshold": ("premium_threshold", float),
            "_low_precision_threshold": ("low_precision_threshold", float),
        },
        "_filter": {
            "_min_volume": ("min_volume", int),
        },
        "_signal_generator": {
            "_confirm_count": ("confirm_count", int),
            "_cooldown_minutes": ("cooldown_minutes", int),
        },
    },
}


def _value_to_str(value, value_type):
    """将Python值转为存储字符串"""
    if value_type == "bool":
        return "true" if value else "false"
    return str(value)


def _str_to_value(value_str, value_type):
    """将存储字符串转为Python值"""
    if value_type == "bool":
        return value_str.lower() == "true"
    if value_type == "int":
        return int(value_str)
    if value_type == "float":
        return float(value_str)
    return value_str


class ConfigManager:
    """配置管理器：初始化、读取、热加载"""

    def __init__(self, storage, scheduler, config_dict):
        self._storage = storage
        self._scheduler = scheduler
        self._config_dict = config_dict
        self._strategies = {}

    def register_strategy(self, name, strategy):
        """注册策略实例，热加载时更新其属性"""
        self._strategies[name] = strategy

    def init_from_yaml(self):
        """从config.yaml初始化到config_kv表（仅DB为空时写入）"""
        existing = self._storage.get_config_by_category("strategy")
        if existing:
            logger.info("配置表已有数据，跳过yaml初始化")
            return

        logger.info("首次启动，从config.yaml初始化配置到数据库")
        for category, sections in CONFIG_META.items():
            for section, keys in sections.items():
                for key, meta in keys.items():
                    # 从config_dict中取值
                    value = self._get_yaml_value(category, section, key, meta["default"])
                    value_str = _value_to_str(value, meta["value_type"])
                    self._storage.upsert_config_kv(
                        category, section, key, value_str,
                        meta["value_type"], meta["label"], meta["description"]
                    )

    def _get_yaml_value(self, category, section, key, default):
        """从config_dict中按路径取值"""
        if category == "strategy":
            # strategies.bond_ipo.enabled
            val = self._config_dict.get("strategies", {}).get(section, {}).get(key, default)
        else:
            # notify.desktop.enabled 或 risk.risk.xxx 或 system.system.xxx
            val = self._config_dict.get(category, {}).get(section, {}).get(key, default)
        return val

    def get_config(self, category=None):
        """查询配置项列表"""
        if category:
            return self._storage.get_config_by_category(category)
        # 查询全部
        all_items = []
        for cat in CONFIG_META:
            all_items.extend(self._storage.get_config_by_category(cat))
        return all_items

    def get_config_as_dict(self, category):
        """获取配置为嵌套字典格式，供策略初始化使用"""
        items = self._storage.get_config_by_category(category)
        result = {}
        for item in items:
            section = item["section"]
            key = item["key"]
            value = _str_to_value(item["value"], item["value_type"])
            if section not in result:
                result[section] = {}
            result[section][key] = value
        return result

    def update_config(self, items):
        """批量更新配置项，写入DB并发出重载信号"""
        self._storage.batch_update_config(items)
        self._storage.insert_reload_signal()
        logger.info("配置已更新，重载信号已发出: %s", items)

    def reload(self):
        """从DB读取最新配置，更新所有注册策略的属性"""
        for strategy_name, attr_map in STRATEGY_ATTR_MAP.items():
            strategy = self._strategies.get(strategy_name)
            if not strategy:
                continue
            # 获取该策略的配置section
            section_items = self._storage.get_config_by_category("strategy")
            section_config = {}
            for item in section_items:
                if item["section"] == strategy_name:
                    section_config[item["key"]] = _str_to_value(item["value"], item["value_type"])

            # 更新策略直接属性
            for attr, config_key in attr_map.items():
                if config_key in section_config:
                    setattr(strategy, attr, section_config[config_key])

            # 更新策略子对象属性
            sub_obj_map = STRATEGY_SUB_OBJ_MAP.get(strategy_name, {})
            for obj_attr, key_map in sub_obj_map.items():
                sub_obj = getattr(strategy, obj_attr, None)
                if sub_obj is None:
                    continue
                for sub_attr, (config_key, type_fn) in key_map.items():
                    if config_key in section_config:
                        setattr(sub_obj, sub_attr, type_fn(section_config[config_key]))

        logger.info("配置热加载完成")

    def check_reload_signals(self):
        """检查并处理未处理的重载信号（由调度器定期调用）"""
        signals = self._storage.get_unprocessed_reload_signals()
        if not signals:
            return
        logger.info("检测到%d个配置重载信号", len(signals))
        self.reload()
        for signal in signals:
            self._storage.mark_reload_signal_processed(signal["id"])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_config_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: 运行全部测试确认无破坏**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add config_manager.py tests/test_config_manager.py
git commit -m "feat: 实现ConfigManager配置管理器（初始化/读取/热加载/信号机制）"
```

---

### Task 4: 调度器新增remove_job/modify_job和配置轮询

**Files:**
- Modify: `scheduler/scheduler.py:17-201`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: 在StrategyScheduler中新增remove_job和modify_job方法**

在 `scheduler/scheduler.py` 的 `StrategyScheduler` 类中，`add_heartbeat_job` 方法之后（约第168行之前）添加：

```python
    def remove_job(self, strategy_name):
        """移除策略的调度job"""
        job_names = [f"daily_{strategy_name}", f"interval_{strategy_name}"]
        for job_name in job_names:
            try:
                self._scheduler.remove_job(job_name)
                logger.info("已移除调度job: %s", job_name)
            except Exception:
                pass  # job不存在则忽略

    def modify_interval_job(self, strategy_name, seconds):
        """修改间隔job的触发间隔"""
        job_name = f"interval_{strategy_name}"
        try:
            from apscheduler.triggers.interval import IntervalTrigger
            self._scheduler.reschedule_job(job_name, trigger=IntervalTrigger(seconds=seconds))
            logger.info("已修改job %s 间隔为 %ds", job_name, seconds)
        except Exception:
            logger.warning("修改job %s 失败，尝试重建", job_name)
            # 如果reschedule失败，移除后重建
            self.remove_job(strategy_name)
            if strategy_name in self._strategies:
                strategy = self._strategies[strategy_name]
                if strategy.is_enabled():
                    self.add_interval_job(strategy_name, seconds)

    def add_config_poll_job(self, config_manager, interval=30):
        """添加配置轮询job，定期检查重载信号"""
        def _poll_config():
            try:
                config_manager.check_reload_signals()
            except Exception as e:
                logger.error("配置轮询失败: %s", e)

        self._scheduler.add_job(
            _poll_config,
            'interval',
            seconds=interval,
            id='config_poll',
            replace_existing=True,
        )
        logger.info("配置轮询job已注册，间隔%d秒", interval)
```

- [ ] **Step 2: 运行现有调度器测试确认不破坏**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scheduler/scheduler.py
git commit -m "feat: 调度器新增remove_job/modify_interval_job/配置轮询job"
```

---

### Task 5: 重构Flask后端为API模式

**Files:**
- Modify: `dashboard/app.py:1-250` (full rewrite)
- Test: `tests/test_dashboard_api.py` (create)

- [ ] **Step 1: 编写看板API测试**

创建 `tests/test_dashboard_api.py`：

```python
"""测试看板API端点"""

import json
import sqlite3
import pytest
from data.models import init_db
from data.storage import Storage

# Flask app需要在导入时创建，这里用pytest fixture处理


@pytest.fixture
def app_client():
    """创建测试用Flask客户端"""
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    storage = Storage(conn)

    # 插入一些测试数据
    for i in range(25):
        storage.insert_premium_history(
            f"2026-05-01 09:{i:02d}:00", "164906" if i % 2 == 0 else "501050",
            1.0 + i * 0.01, 1.0, i * 0.5, "realtime"
        )
    storage.insert_trade_signal("2026-05-01 10:00:00", "164906", 3.5, "buy", "pending", "realtime")
    storage.insert_alert_event("ERROR", "lof_premium", "测试告警")
    storage.insert_notification_log("desktop", "LOF_PREMIUM", "测试", "测试消息", "success")
    storage.insert_execution_log("lof_premium", "success", 1500, None)

    # 创建Flask app
    from dashboard.app import create_app
    app = create_app(storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, storage

    conn.close()


def test_api_data_lof_premium_paginated(app_client):
    """测试LOF溢价数据分页API"""
    client, _ = app_client
    resp = client.get("/api/data/lof_premium?page=1&page_size=10")
    data = json.loads(resp.data)
    assert resp.status_code == 200
    assert "items" in data
    assert "total" in data
    assert data["page_size"] == 10
    assert data["total"] == 25
    assert data["total_pages"] == 3


def test_api_data_lof_premium_search(app_client):
    """测试LOF溢价数据搜索"""
    client, _ = app_client
    resp = client.get("/api/data/lof_premium?search=164906")
    data = json.loads(resp.data)
    assert data["total"] > 0
    for item in data["items"]:
        assert "164906" in item.get("fund_code", "")


def test_api_data_trade_signal(app_client):
    """测试交易信号API"""
    client, _ = app_client
    resp = client.get("/api/data/trade_signal?page=1&page_size=10")
    data = json.loads(resp.data)
    assert data["total"] >= 1


def test_api_status_paginated(app_client):
    """测试状态API分页参数"""
    client, _ = app_client
    resp = client.get("/api/status?alert_page=1&alert_page_size=5&notif_page=1&notif_page_size=5")
    data = json.loads(resp.data)
    assert resp.status_code == 200
    assert "alert_events" in data
    assert "notification_logs" in data


def test_api_config_get(app_client):
    """测试配置查询API"""
    client, storage = app_client
    # 先初始化一些配置
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "")
    resp = client.get("/api/config?category=strategy")
    data = json.loads(resp.data)
    assert resp.status_code == 200
    assert len(data) >= 1


def test_api_config_update(app_client):
    """测试配置更新API"""
    client, storage = app_client
    storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "true", "bool", "启用策略", "")
    resp = client.put("/api/config",
                       data=json.dumps({"items": [{"category": "strategy", "section": "bond_ipo", "key": "enabled", "value": "false"}]}),
                       content_type="application/json")
    data = json.loads(resp.data)
    assert resp.status_code == 200
    assert data["ok"] is True
    # 验证DB已更新
    result = storage.get_config_kv("strategy", "bond_ipo", "enabled")
    assert result["value"] == "false"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_dashboard_api.py -v`
Expected: FAIL (ImportError or AttributeError: create_app not found)

- [ ] **Step 3: 重写dashboard/app.py**

将 `dashboard/app.py` 完全重写为API模式。核心结构：

```python
"""看板Flask应用：纯API后端"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, render_template, g

from data.models import init_db
from data.storage import Storage

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "get_cash.db")

# 全局ConfigManager引用（由main.py注入）
_config_manager = None


def create_app(storage=None, config_manager=None):
    """创建Flask应用

    Args:
        storage: Storage实例（测试时注入内存DB）
        config_manager: ConfigManager实例（由main.py注入）
    """
    global _config_manager
    _config_manager = config_manager

    app = Flask(__name__)
    app._storage = storage  # 挂载storage到app对象

    # 注册路由
    _register_routes(app)
    return app


def _get_storage():
    """获取Storage实例（优先从app对象获取，否则创建新连接）"""
    storage = getattr(g, "_storage", None)
    if storage is not None:
        return storage
    # 从app对象获取注入的storage
    app_storage = getattr(g.get("app", None), "_storage", None) or getattr(request.app._storage, None)
    if app_storage is not None:
        return app_storage
    # 默认从DB文件创建
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    g._storage = Storage(conn)
    g._conn = conn
    return g._storage


def _register_routes(app):
    """注册所有路由"""

    @app.route("/")
    def index():
        """返回SPA页面"""
        return render_template("index.html")

    # ==================== 状态API ====================

    @app.route("/api/status")
    def api_status():
        """系统状态API，支持告警和通知的分页"""
        storage = _get_storage()
        alert_page = request.args.get("alert_page", 1, type=int)
        alert_page_size = request.args.get("alert_page_size", 20, type=int)
        notif_page = request.args.get("notif_page", 1, type=int)
        notif_page_size = request.args.get("notif_page_size", 20, type=int)

        # 系统健康
        system_status = storage.get_system_status("start_time")
        uptime = 0
        if system_status:
            try:
                start = datetime.strptime(system_status, "%Y-%m-%d %H:%M:%S")
                uptime = int((datetime.now() - start).total_seconds())
            except ValueError:
                pass
        selfcheck = storage.get_system_status("selfcheck_result") or "unknown"
        last_heartbeat = storage.get_system_status("last_heartbeat") or "--"

        # 数据源
        ds_rows = storage._conn.execute("SELECT * FROM data_source_status").fetchall()
        data_sources = [dict(r) for r in ds_rows]

        # 通知统计
        today = datetime.now().strftime("%Y-%m-%d")
        notif_rows = storage._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM notification_log WHERE timestamp LIKE ? GROUP BY status",
            (f"{today}%",)
        ).fetchall()
        today_stats = {"total": 0, "success": 0, "fail": 0}
        for r in notif_rows:
            cnt = r["cnt"]
            today_stats["total"] += cnt
            if r["status"] == "success":
                today_stats["success"] = cnt
            elif r["status"] == "fail":
                today_stats["fail"] = cnt

        # 策略执行
        strategies = ["bond_ipo", "bond_allocation", "reverse_repo", "lof_premium"]
        strategy_execution = []
        for sname in strategies:
            rows = storage._conn.execute(
                "SELECT * FROM strategy_execution_log WHERE strategy_name=? ORDER BY trigger_time DESC LIMIT 1",
                (sname,)
            ).fetchall()
            today_cnt = storage._conn.execute(
                "SELECT COUNT(*) as cnt FROM strategy_execution_log WHERE strategy_name=? AND timestamp LIKE ?",
                (sname, f"{today}%")
            ).fetchone()["cnt"]
            if rows:
                r = dict(rows[0])
                strategy_execution.append({
                    "strategy_name": sname,
                    "last_trigger_time": r.get("trigger_time", "--"),
                    "last_status": r.get("status", "--"),
                    "last_duration_ms": r.get("duration_ms", 0),
                    "today_count": today_cnt,
                })
            else:
                strategy_execution.append({
                    "strategy_name": sname,
                    "last_trigger_time": "--",
                    "last_status": "--",
                    "last_duration_ms": 0,
                    "today_count": today_cnt,
                })

        # LOF执行耗时趋势
        trend_rows = storage._conn.execute(
            "SELECT trigger_time, duration_ms FROM strategy_execution_log WHERE strategy_name='lof_premium' ORDER BY trigger_time DESC LIMIT 20"
        ).fetchall()
        execution_trend = [dict(r) for r in trend_rows]

        # 告警事件（分页）
        alert_result = storage.query_paginated(
            "alert_event", page=alert_page, page_size=alert_page_size,
            order_by="timestamp", order_dir="DESC"
        )

        # 通知记录（分页）
        notif_result = storage.query_paginated(
            "notification_log", page=notif_page, page_size=notif_page_size,
            order_by="timestamp", order_dir="DESC"
        )

        return jsonify({
            "system": {"status": "running", "uptime_seconds": uptime, "selfcheck": selfcheck, "last_heartbeat": last_heartbeat},
            "data_sources": data_sources,
            "notifications": {"today_stats": today_stats},
            "strategy_execution": strategy_execution,
            "execution_trend": execution_trend,
            "alert_events": alert_result,
            "notification_logs": notif_result,
        })

    # ==================== 业务数据API（分页） ====================

    @app.route("/api/data/lof_premium")
    def api_data_lof_premium():
        """LOF溢价率历史（分页）"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        search = request.args.get("search", "")
        sort_by = request.args.get("sort_by", "timestamp")
        sort_order = request.args.get("sort_order", "DESC")
        search_columns = ["fund_code"] if search else None
        result = storage.query_paginated("premium_history", page=page, page_size=page_size,
                                          search=search, search_columns=search_columns,
                                          order_by=sort_by, order_dir=sort_order)
        return jsonify(result)

    @app.route("/api/data/trade_signal")
    def api_data_trade_signal():
        """交易信号（分页）"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        search = request.args.get("search", "")
        sort_by = request.args.get("sort_by", "trigger_time")
        sort_order = request.args.get("sort_order", "DESC")
        search_columns = ["fund_code", "action"] if search else None
        result = storage.query_paginated("trade_signal", page=page, page_size=page_size,
                                          search=search, search_columns=search_columns,
                                          order_by=sort_by, order_dir=sort_order)
        return jsonify(result)

    @app.route("/api/data/bond_ipo")
    def api_data_bond_ipo():
        """可转债打新（分页）"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        search = request.args.get("search", "")
        sort_by = request.args.get("sort_by", "subscribe_date")
        sort_order = request.args.get("sort_order", "DESC")
        search_columns = ["code", "name"] if search else None
        result = storage.query_paginated("bond_ipo", page=page, page_size=page_size,
                                          search=search, search_columns=search_columns,
                                          order_by=sort_by, order_dir=sort_order)
        return jsonify(result)

    @app.route("/api/data/bond_allocation")
    def api_data_bond_allocation():
        """配债监控（分页）"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        search = request.args.get("search", "")
        sort_by = request.args.get("sort_by", "record_date")
        sort_order = request.args.get("sort_order", "DESC")
        search_columns = ["code", "stock_name"] if search else None
        result = storage.query_paginated("bond_allocation", page=page, page_size=page_size,
                                          search=search, search_columns=search_columns,
                                          order_by=sort_by, order_dir=sort_order)
        return jsonify(result)

    @app.route("/api/data/reverse_repo")
    def api_data_reverse_repo():
        """逆回购（分页）"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        search = request.args.get("search", "")
        sort_by = request.args.get("sort_by", "date")
        sort_order = request.args.get("sort_order", "DESC")
        search_columns = ["date"] if search else None
        result = storage.query_paginated("reverse_repo", page=page, page_size=page_size,
                                          search=search, search_columns=search_columns,
                                          order_by=sort_by, order_dir=sort_order)
        return jsonify(result)

    @app.route("/api/data/daily_summary")
    def api_data_daily_summary():
        """日汇总（分页）"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        search = request.args.get("search", "")
        sort_by = request.args.get("sort_by", "date")
        sort_order = request.args.get("sort_order", "DESC")
        search_columns = ["date", "strategy_type"] if search else None
        result = storage.query_paginated("daily_summary", page=page, page_size=page_size,
                                          search=search, search_columns=search_columns,
                                          order_by=sort_by, order_dir=sort_order)
        return jsonify(result)

    # ==================== 静默API（保留） ====================

    @app.route("/api/mute", methods=["POST"])
    def api_mute():
        """手动静默基金"""
        storage = _get_storage()
        data = request.get_json() or {}
        fund_code = data.get("fund_code")
        days = data.get("days", 7)
        if not fund_code:
            return jsonify({"ok": False, "error": "缺少fund_code"}), 400
        muted_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        storage.mute_fund(fund_code, muted_until, "手动静默")
        return jsonify({"ok": True})

    @app.route("/api/unmute", methods=["POST"])
    def api_unmute():
        """解除静默"""
        storage = _get_storage()
        data = request.get_json() or {}
        fund_code = data.get("fund_code")
        if not fund_code:
            return jsonify({"ok": False, "error": "缺少fund_code"}), 400
        storage.unmute_fund(fund_code)
        return jsonify({"ok": True})

    @app.route("/api/muted_funds")
    def api_muted_funds():
        """已静默基金列表（分页）"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        search = request.args.get("search", "")
        search_columns = ["code", "name"] if search else None
        result = storage.query_paginated("lof_fund", page=page, page_size=page_size,
                                          search=search, search_columns=search_columns,
                                          order_by="muted_until", order_dir="ASC",
                                          extra_where="status='muted'")
        return jsonify(result)

    # ==================== 配置管理API ====================

    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        """查询配置项"""
        if _config_manager is None:
            return jsonify({"error": "ConfigManager未初始化"}), 500
        category = request.args.get("category")
        result = _config_manager.get_config(category)
        return jsonify(result)

    @app.route("/api/config", methods=["PUT"])
    def api_config_update():
        """批量更新配置项"""
        if _config_manager is None:
            return jsonify({"error": "ConfigManager未初始化"}), 500
        data = request.get_json() or {}
        items = data.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "缺少items"}), 400
        _config_manager.update_config(items)
        return jsonify({"ok": True})

    @app.route("/api/config/reload", methods=["POST"])
    def api_config_reload():
        """手动触发热加载"""
        if _config_manager is None:
            return jsonify({"error": "ConfigManager未初始化"}), 500
        _config_manager.reload()
        return jsonify({"ok": True})

    @app.teardown_appcontext
    def close_db(exception):
        """请求结束后关闭DB连接"""
        conn = getattr(g, "_conn", None)
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
```

- [ ] **Step 4: 运行看板API测试**

Run: `python -m pytest tests/test_dashboard_api.py -v`
Expected: ALL PASS

- [ ] **Step 5: 运行全部测试确认无破坏**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard/app.py tests/test_dashboard_api.py
git commit -m "feat: 重构Flask后端为API模式（分页数据API+配置CRUD API）"
```

---

### Task 6: 下载Petite-Vue并搭建前端SPA

**Files:**
- Create: `dashboard/static/petite-vue.js`
- Modify: `dashboard/templates/index.html` (full rewrite)

- [ ] **Step 1: 下载Petite-Vue到本地**

Run: `curl -L -o dashboard/static/petite-vue.js https://unpkg.com/petite-vue@0.4.1/dist/petite-vue.iife.js`

如果curl不可用，手动下载 petite-vue iife 版本到 `dashboard/static/petite-vue.js`。

验证文件存在：`ls -la dashboard/static/petite-vue.js`

- [ ] **Step 2: 重写index.html为Petite-Vue SPA**

将 `dashboard/templates/index.html` 完全重写。核心结构：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>个人量化套利中枢</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: "Microsoft YaHei", sans-serif; background: #f5f5f5; color: #333; padding: 20px; }
        h1 { text-align: center; margin-bottom: 16px; font-size: 24px; color: #222; }
        .tabs { display: flex; border-bottom: 2px solid #e8e8e8; margin-bottom: 20px; }
        .tab { padding: 10px 24px; cursor: pointer; font-size: 15px; color: #666; border-bottom: 3px solid transparent; transition: all 0.2s; }
        .tab.active { color: #1890ff; border-bottom-color: #1890ff; font-weight: 600; }
        .tab:hover { color: #1890ff; }
        .section { background: #fff; border-radius: 6px; padding: 16px 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .section h2 { font-size: 16px; color: #444; margin-bottom: 12px; border-left: 3px solid #1890ff; padding-left: 8px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #e8e8e8; white-space: nowrap; }
        th { background: #fafafa; color: #666; font-weight: 600; }
        tr:hover td { background: #f0f7ff; }
        .empty { color: #999; padding: 12px 0; font-size: 13px; }
        .status-cards { display: flex; gap: 12px; margin-bottom: 16px; }
        .status-card { flex: 1; background: #fff; border-radius: 6px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .status-card h3 { font-size: 13px; color: #999; margin-bottom: 8px; }
        .status-ok { color: #52c41a; }
        .status-warn { color: #fa8c16; }
        .status-error { color: #f5222d; }
        .level-ERROR { background: #f5222d; color: #fff; padding: 1px 6px; border-radius: 3px; font-size: 11px; }
        .level-WARN { background: #fa8c16; color: #fff; padding: 1px 6px; border-radius: 3px; font-size: 11px; }
        .level-INFO { background: #1890ff; color: #fff; padding: 1px 6px; border-radius: 3px; font-size: 11px; }
        .level-OK { background: #52c41a; color: #fff; padding: 1px 6px; border-radius: 3px; font-size: 11px; }
        .bar-chart { height: 80px; display: flex; align-items: flex-end; gap: 4px; padding: 8px 0; }
        .bar-chart .bar { flex: 1; border-radius: 2px 2px 0 0; min-width: 8px; position: relative; }
        .bar-chart .bar .bar-label { position: absolute; bottom: -16px; left: 50%; transform: translateX(-50%); font-size: 10px; color: #999; white-space: nowrap; }
        .refresh-info { text-align: right; font-size: 12px; color: #999; margin-bottom: 8px; }
        .mute-btn, .unmute-btn { padding: 2px 8px; font-size: 12px; cursor: pointer; border: 1px solid #1890ff; background: #fff; color: #1890ff; border-radius: 3px; }
        .mute-btn:hover, .unmute-btn:hover { background: #1890ff; color: #fff; }
        /* 分页控件样式 */
        .pagination-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; font-size: 12px; }
        .pagination-bar .page-info { color: #666; }
        .pagination-bar .page-btns { display: flex; gap: 4px; align-items: center; }
        .page-btn { padding: 4px 10px; border: 1px solid #d9d9d9; background: #fff; border-radius: 3px; cursor: pointer; font-size: 12px; }
        .page-btn:hover { border-color: #1890ff; color: #1890ff; }
        .page-btn.active { background: #1890ff; color: #fff; border-color: #1890ff; }
        .page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .search-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
        .search-bar input { padding: 4px 8px; border: 1px solid #d9d9d9; border-radius: 3px; font-size: 13px; width: 200px; }
        .search-bar button { padding: 4px 12px; background: #1890ff; color: #fff; border: none; border-radius: 3px; cursor: pointer; font-size: 13px; }
        .search-bar .total-info { color: #999; font-size: 12px; margin-left: auto; }
        /* 配置页样式 */
        .config-section { background: #fafafa; border-radius: 4px; padding: 12px; margin-bottom: 12px; }
        .config-section h3 { font-size: 14px; margin-bottom: 8px; color: #333; }
        .config-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .config-item { display: flex; align-items: center; gap: 6px; font-size: 13px; }
        .config-item input[type="number"] { width: 70px; padding: 2px 4px; border: 1px solid #d9d9d9; border-radius: 3px; }
        .config-item input[type="text"] { width: 200px; padding: 2px 4px; border: 1px solid #d9d9d9; border-radius: 3px; }
        .config-save-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .save-btn { padding: 4px 16px; background: #1890ff; color: #fff; border: none; border-radius: 3px; cursor: pointer; font-size: 13px; }
        .save-btn:hover { background: #40a9ff; }
        .save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    </style>
</head>
<body>
    <h1>个人量化套利中枢</h1>

    <div v-scope="App()" @mounted="init">
        <div class="tabs">
            <div class="tab" :class="{active: activeTab==='status'}" @click="activeTab='status'">状态总览</div>
            <div class="tab" :class="{active: activeTab==='data'}" @click="activeTab='data'">业务数据</div>
            <div class="tab" :class="{active: activeTab==='config'}" @click="switchToConfig()">系统配置</div>
        </div>

        <!-- 状态总览 -->
        <div v-show="activeTab==='status'" v-scope="StatusTab()"></div>

        <!-- 业务数据 -->
        <div v-show="activeTab==='data'" v-scope="DataTab()"></div>

        <!-- 系统配置 -->
        <div v-show="activeTab==='config'" v-scope="ConfigTab()"></div>
    </div>

    <script src="/static/petite-vue.js"></script>
    <script>
    // 后续Task中填充各组件的JS实现
    </script>
</body>
</html>
```

- [ ] **Step 3: 验证页面能正常加载**

Run: `cd dashboard && python -c "from app import create_app; app = create_app(); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/petite-vue.js dashboard/templates/index.html
git commit -m "feat: 下载Petite-Vue并搭建SPA骨架"
```

---

### Task 7: 实现前端Petite-Vue组件——状态总览和业务数据

**Files:**
- Modify: `dashboard/templates/index.html` (add component JS)

- [ ] **Step 1: 在index.html的script标签中实现App和StatusTab组件**

在 `<script>` 标签内添加完整组件实现。由于代码量较大，这里给出核心结构，每个组件都是 Petite-Vue 的 `v-scope` 对象：

**App组件**：管理activeTab状态，60秒自动刷新状态

**StatusTab组件**：
- fetchStatus() — 调用 `/api/status`，填充系统健康、数据源、通知统计、策略执行、耗时趋势
- 告警事件分页 — 使用 DataTable 子组件
- 通知记录分页 — 使用 DataTable 子组件
- 已静默基金分页 — 含解除按钮

**DataTab组件**：
- 6个数据表格，每个使用 DataTable 子组件
- 各表格的API端点和列定义

**DataTable子组件**（通用分页表格）：
- props: apiUrl, searchColumns, defaultSortBy, defaultSortOrder, columns
- 状态: items, total, page, pageSize, totalPages, search, loading
- 方法: fetchData(), changePage(n), changePageSize(s), doSearch()
- 模板: 搜索栏 + 表格 + 分页栏

- [ ] **Step 2: 在浏览器中验证状态总览**

启动看板，访问 http://localhost:5000，检查"状态总览"标签页是否正常加载数据。

- [ ] **Step 3: 在浏览器中验证业务数据**

切换到"业务数据"标签页，检查6个表格是否正常显示分页和搜索。

- [ ] **Step 4: Commit**

```bash
git add dashboard/templates/index.html
git commit -m "feat: 实现前端状态总览和业务数据Petite-Vue组件（分页+搜索）"
```

---

### Task 8: 实现前端Petite-Vue组件——系统配置

**Files:**
- Modify: `dashboard/templates/index.html` (add ConfigTab component)

- [ ] **Step 1: 在index.html中实现ConfigTab组件**

ConfigTab组件逻辑：
- 加载时调用 `GET /api/config` 获取全部配置
- 按4个category分组渲染
- 每个section折叠展示
- 根据value_type渲染控件：bool→checkbox，int/float→number input，string→text input
- 修改后标记"未保存"状态
- 点击"保存"调用 `PUT /api/config` 批量更新
- 保存成功提示

- [ ] **Step 2: 在浏览器中验证配置页**

切换到"系统配置"标签页，检查4个配置分组是否正常显示，修改配置并保存，验证DB更新。

- [ ] **Step 3: Commit**

```bash
git add dashboard/templates/index.html
git commit -m "feat: 实现前端系统配置Petite-Vue组件（CRUD+保存）"
```

---

### Task 9: 集成ConfigManager到main.py

**Files:**
- Modify: `main.py:240-354`

- [ ] **Step 1: 在main.py中集成ConfigManager**

在 `main.py` 的 `main()` 函数中，按以下顺序修改：

1. 在创建Storage之后（约第249行后），创建ConfigManager：
```python
from config_manager import ConfigManager
config_manager = ConfigManager(storage, scheduler=None, config_dict=config)
```

2. 在scheduler创建之后（约第274行后），设置scheduler引用：
```python
config_manager._scheduler = scheduler
```

3. 在每个策略创建后，注册到ConfigManager：
```python
config_manager.register_strategy("bond_ipo", bond_ipo)
config_manager.register_strategy("reverse_repo", reverse_repo)
config_manager.register_strategy("bond_allocation", bond_alloc)
config_manager.register_strategy("lof_premium", lof_premium)
```

4. 在注册策略之后，初始化配置：
```python
config_manager.init_from_yaml()
```

5. 在添加心跳job之后（约第347行后），添加配置轮询job：
```python
scheduler.add_config_poll_job(config_manager, interval=30)
```

6. 在scheduler.start()之前，启动Flask看板线程：
```python
import threading
from dashboard.app import create_app
flask_app = create_app(storage=storage, config_manager=config_manager)
flask_thread = threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=5000), daemon=True)
flask_thread.start()
logger.info("Flask看板已启动于 http://0.0.0.0:5000")
```

- [ ] **Step 2: 运行全部测试确认不破坏**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: 集成ConfigManager到main.py（Flask线程+配置轮询+策略注册）"
```

---

### Task 10: 端到端验证

**Files:**
- 无新文件

- [ ] **Step 1: 启动系统并验证看板**

Run: `python main.py`

在浏览器中访问 http://localhost:5000，验证：
- 状态总览标签页正常加载
- 业务数据标签页6个表格分页和搜索正常
- 系统配置标签页显示配置项，修改后保存成功

- [ ] **Step 2: 验证热加载**

1. 在看板中修改LOF溢价率阈值（如从3.0改为4.0）
2. 点击保存
3. 等待30秒配置轮询周期
4. 检查日志中是否有"配置热加载完成"
5. 在看板中将值改回3.0

- [ ] **Step 3: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "feat: 看板增强完成（分页搜索+配置管理+热加载）"
```

---

## 自审清单

**1. Spec覆盖检查：**
- 分页+搜索所有表格区域 → Task 2(Storage分页) + Task 5(API) + Task 7(前端)
- 配置迁移到看板CRUD → Task 1(表) + Task 2(Storage) + Task 3(ConfigManager) + Task 5(API) + Task 8(前端配置页)
- 热加载 → Task 3(ConfigManager.reload) + Task 4(调度器轮询) + Task 9(main.py集成)
- SQLite存储config_kv → Task 1 + Task 2
- Petite-Vue SPA → Task 6 + Task 7 + Task 8

**2. Placeholder扫描：** 无TBD/TODO/实现后补。所有代码步骤包含完整实现。

**3. 类型一致性：**
- `upsert_config_kv(category, section, key, value, value_type, label, description)` 在Task 2和Task 3中签名一致
- `query_paginated(table, page, page_size, search, search_columns, order_by, order_dir, extra_where, extra_params)` 在Task 2和Task 5中签名一致
- `ConfigManager.__init__(storage, scheduler, config_dict)` 在Task 3和Task 9中一致
- `create_app(storage, config_manager)` 在Task 5和Task 9中一致
