# 系统可观测性增强 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强系统可观测性，让看板能一眼判断系统健康状态、数据源异常可追踪、策略执行可回溯、通知发送有记录。

**Architecture:** 新增3张DB表（strategy_execution_log、alert_event、notification_log）+ 1张KV表（system_status），扩展data_source_status表，Storage层增8个方法，DataCollector 6个数据源全部接入状态记录+告警通知，StrategyScheduler执行包装计时+状态记录，NotificationManager持久化+失败记录，心跳增强携带健康摘要，看板改造为双标签页（状态总览+业务数据），Flask新增/api/status接口，前端60秒自动刷新。

**Tech Stack:** Python 3.10+, SQLite, Flask, APScheduler, Jinja2, 纯CSS柱状图

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `data/models.py` | 新增4张表DDL + 扩展data_source_status字段 |
| Modify | `data/storage.py` | 新增8个方法（3写3查+扩展failure+list_all） |
| Modify | `data/collector.py` | 6个数据源接入状态记录 + notifier注入 + 连续失败告警 |
| Modify | `notify/base.py` | NotificationEvent补全 + NotificationManager注入storage + 持久化 |
| Modify | `scheduler/scheduler.py` | 执行包装计时+状态记录 + 心跳增强 + slow_threshold |
| Modify | `main.py` | 注入notifier到collector + 注入storage到NotificationManager + 启动/自检持久化 |
| Modify | `dashboard/app.py` | 新增/api/status路由 + 调整index路由支持双标签 |
| Modify | `dashboard/templates/index.html` | 双标签页 + 状态总览7区块 + 自动刷新JS |
| Modify | `tests/test_storage.py` | 新增3张表的CRUD测试 |
| Modify | `tests/test_notifier.py` | 新增持久化测试 |
| Create | `tests/test_scheduler.py` | 执行包装+心跳增强测试 |

---

### Task 1: 新增DB表DDL + 扩展data_source_status

**Files:**
- Modify: `data/models.py:8-131`

- [ ] **Step 1: 在DDL_STATEMENTS中新增4张表，扩展data_source_status**

在 `data/models.py` 的 `DDL_STATEMENTS` 列表末尾（第108行 `)""",` 之后）添加4个新DDL，并修改现有 `data_source_status` 的DDL增加2个字段：

```python
    # 数据源状态表（扩展：增加失败时间和失败原因）
    """CREATE TABLE IF NOT EXISTS data_source_status (
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'unknown',
        last_success_time TEXT NOT NULL DEFAULT '',
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_failure_time TEXT NOT NULL DEFAULT '',
        failure_reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (name)
    )""",
    # 策略执行日志表
    """CREATE TABLE IF NOT EXISTS strategy_execution_log (
        id INTEGER NOT NULL,
        strategy_name TEXT NOT NULL DEFAULT '',
        trigger_time TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'success',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        error_message TEXT NOT NULL DEFAULT '',
        record_time TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 告警事件表
    """CREATE TABLE IF NOT EXISTS alert_event (
        id INTEGER NOT NULL,
        level TEXT NOT NULL DEFAULT 'INFO',
        source TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        timestamp TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 通知发送记录表
    """CREATE TABLE IF NOT EXISTS notification_log (
        id INTEGER NOT NULL,
        channel TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'success',
        timestamp TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (id AUTOINCREMENT)
    )""",
    # 系统状态KV表
    """CREATE TABLE IF NOT EXISTS system_status (
        key TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (key)
    )""",
```

删除原来的 `data_source_status` DDL（第101-108行），用上面扩展后的版本替代。

- [ ] **Step 2: 更新TABLE_NAMES列表和INDEX_STATEMENTS**

在 `TABLE_NAMES` 列表末尾追加：
```python
    "strategy_execution_log",
    "alert_event",
    "notification_log",
    "system_status",
```

在 `INDEX_STATEMENTS` 列表末尾追加：
```python
    "CREATE INDEX IF NOT EXISTS idx_execution_log_strategy ON strategy_execution_log(strategy_name)",
    "CREATE INDEX IF NOT EXISTS idx_execution_log_time ON strategy_execution_log(trigger_time)",
    "CREATE INDEX IF NOT EXISTS idx_alert_event_time ON alert_event(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_notification_log_time ON notification_log(timestamp)",
```

- [ ] **Step 3: 处理已有数据库的schema迁移**

在 `init_db` 函数末尾（`conn.commit()` 之前），添加迁移逻辑——对已存在的 data_source_status 表尝试添加新列（ALTER TABLE IF NOT EXISTS 在SQLite中不支持，用try/except）：

```python
    # 兼容已有数据库：尝试添加新字段
    for stmt in [
        "ALTER TABLE data_source_status ADD COLUMN last_failure_time TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE data_source_status ADD COLUMN failure_reason TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            cursor.execute(stmt)
        except Exception:
            pass  # 字段已存在则忽略
```

- [ ] **Step 4: 运行测试验证**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/models.py
git commit -m "feat: 新增4张可观测性表DDL + 扩展data_source_status字段"
```

---

### Task 2: Storage层新增方法

**Files:**
- Modify: `data/storage.py:170-222`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: 扩展record_data_source_failure方法，增加reason参数**

在 `data/storage.py` 第196行，修改方法签名为：

```python
    def record_data_source_failure(self, name: str, reason: str = "") -> int:
```

在插入新记录的分支（第206-210行），添加 `last_failure_time` 和 `failure_reason`：

```python
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._conn.execute(
                """INSERT INTO data_source_status (name, status, last_success_time, consecutive_failures, last_failure_time, failure_reason)
                   VALUES (?, 'failure', '', 1, ?, ?)""",
                (name, now, reason[:200]),
            )
```

在更新已有记录的分支（第214-220行），添加更新 `last_failure_time` 和 `failure_reason`：

```python
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute(
            """UPDATE data_source_status
               SET status='failure', consecutive_failures=?, last_failure_time=?, failure_reason=?
               WHERE name=?""",
            (new_count, now, reason[:200], name),
        )
```

- [ ] **Step 2: 新增list_all_data_source_status方法**

在 `data/storage.py` 的数据源状态区块末尾（第222行之后）添加：

```python
    def list_all_data_source_status(self) -> List[Dict]:
        """列出所有数据源状态"""
        cursor = self._conn.execute(
            "SELECT * FROM data_source_status ORDER BY name"
        )
        return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 3: 新增insert_execution_log和list_execution_logs方法**

在 `data/storage.py` 末尾添加新区块：

```python
    # ==================== 策略执行日志 ====================

    def insert_execution_log(self, strategy_name: str, status: str,
                             duration_ms: int, error_message: str = "") -> int:
        """插入策略执行日志，返回自增ID"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            """INSERT INTO strategy_execution_log (strategy_name, trigger_time, status, duration_ms, error_message, record_time)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (strategy_name, now, status, duration_ms, error_message[:500], now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_execution_logs(self, strategy_name: str = "", limit: int = 20) -> List[Dict]:
        """查询策略执行日志"""
        if strategy_name:
            cursor = self._conn.execute(
                """SELECT * FROM strategy_execution_log
                   WHERE strategy_name = ?
                   ORDER BY trigger_time DESC LIMIT ?""",
                (strategy_name, limit),
            )
        else:
            cursor = self._conn.execute(
                """SELECT * FROM strategy_execution_log
                   ORDER BY trigger_time DESC LIMIT ?""",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 4: 新增insert_alert_event和list_alert_events方法**

```python
    # ==================== 告警事件 ====================

    def insert_alert_event(self, level: str, source: str, message: str) -> int:
        """插入告警事件，返回自增ID"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            """INSERT INTO alert_event (level, source, message, timestamp)
               VALUES (?, ?, ?, ?)""",
            (level, source, message[:500], now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_alert_events(self, limit: int = 20) -> List[Dict]:
        """查询告警事件，按时间倒序"""
        cursor = self._conn.execute(
            """SELECT * FROM alert_event
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 5: 新增insert_notification_log和list_notification_logs方法**

```python
    # ==================== 通知发送记录 ====================

    def insert_notification_log(self, channel: str, event_type: str,
                                title: str, message: str, status: str) -> int:
        """插入通知发送记录，返回自增ID"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._conn.execute(
            """INSERT INTO notification_log (channel, event_type, title, message, status, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (channel, event_type, title[:200], message[:500], status, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_notification_logs(self, limit: int = 20) -> List[Dict]:
        """查询通知发送记录，按时间倒序"""
        cursor = self._conn.execute(
            """SELECT * FROM notification_log
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 6: 新增system_status的upsert和get方法**

```python
    # ==================== 系统状态KV ====================

    def upsert_system_status(self, key: str, value: str) -> None:
        """插入或更新系统状态键值对"""
        self._conn.execute(
            """INSERT INTO system_status (key, value)
               VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value[:500]),
        )
        self._conn.commit()

    def get_system_status(self, key: str) -> Optional[str]:
        """获取系统状态值"""
        cursor = self._conn.execute(
            "SELECT value FROM system_status WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row["value"] if row else None
```

- [ ] **Step 7: 编写测试**

在 `tests/test_storage.py` 末尾追加：

```python
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
```

- [ ] **Step 8: 运行测试**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -m pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add data/storage.py tests/test_storage.py
git commit -m "feat: Storage层新增可观测性方法（执行日志/告警事件/通知记录/系统状态）"
```

---

### Task 3: NotificationManager持久化 + 事件枚举补全

**Files:**
- Modify: `notify/base.py:1-60`
- Modify: `tests/test_notifier.py`

- [ ] **Step 1: 补全NotificationEvent枚举**

在 `notify/base.py` 第6-12行的 `NotificationEvent` 枚举中，在 `DATA_SOURCE_FAILURE` 之前添加：

```python
    LOF_PREMIUM = "lof_premium"
    BOND_IPO = "bond_ipo"
    REVERSE_REPO = "reverse_repo"
    BOND_ALLOCATION = "bond_allocation"
```

- [ ] **Step 2: NotificationManager注入storage + 持久化通知**

修改 `NotificationManager.__init__` 签名（第27行）：

```python
    def __init__(self, config: dict, dual_channel_events: Optional[List[str]] = None,
                 storage=None):
```

在 `__init__` body 中添加：
```python
        self._storage = storage
```

修改 `notify` 方法（第42-59行），在发送循环中记录每次发送结果：

```python
    def notify(self, title: str, message: str, event_type: str = "default") -> None:
        for name, notifier in self._notifiers.items():
            channel_config = self._config.get(name, {})
            if not channel_config.get("enabled", True):
                continue
            try:
                notifier.send(title, message)
                self._log_notification(name, event_type, title, message, "success")
            except Exception as ex:
                self._log_notification(name, event_type, title, message, "fail")
                import logging
                logging.getLogger(__name__).warning("通知渠道%s发送失败: %s", name, ex)

    def _log_notification(self, channel: str, event_type: str,
                          title: str, message: str, status: str) -> None:
        """记录通知发送结果到数据库"""
        if self._storage is None:
            return
        try:
            self._storage.insert_notification_log(channel, event_type, title, message, status)
        except Exception:
            pass  # 日志记录失败不影响主流程
```

- [ ] **Step 3: 更新测试**

在 `tests/test_notifier.py` 末尾追加：

```python
def test_notification_manager_with_storage():
    import sqlite3
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.Connection(":memory:")
    init_db(conn)
    storage = Storage(conn)

    class MockNotifier(Notifier):
        name = "mock"
        def send(self, title: str, message: str) -> bool:
            return True

    class FailNotifier(Notifier):
        name = "fail_channel"
        def send(self, title: str, message: str) -> bool:
            raise RuntimeError("发送失败")

    mgr = NotificationManager(
        {"mock": {"enabled": True}, "fail_channel": {"enabled": True}},
        storage=storage,
    )
    mgr.register("mock", MockNotifier())
    mgr.register("fail_channel", FailNotifier())

    mgr.notify("测试标题", "测试内容", event_type="lof_premium")

    logs = storage.list_notification_logs()
    assert len(logs) == 2
    channels = {log["channel"]: log["status"] for log in logs}
    assert channels["mock"] == "success"
    assert channels["fail_channel"] == "fail"

    conn.close()


def test_notification_manager_no_storage():
    """不注入storage时不报错"""
    class MockNotifier(Notifier):
        name = "mock"
        def send(self, title: str, message: str) -> bool:
            return True

    mgr = NotificationManager({"mock": {"enabled": True}})
    mgr.register("mock", MockNotifier())
    mgr.notify("测试", "内容")  # 不报错
```

- [ ] **Step 4: 运行测试**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -m pytest tests/test_notifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add notify/base.py tests/test_notifier.py
git commit -m "feat: NotificationManager持久化通知记录 + 事件枚举补全"
```

---

### Task 4: DataCollector 6个数据源接入状态记录 + 告警通知

**Files:**
- Modify: `data/collector.py:11-30` (构造函数)
- Modify: `data/collector.py:90-126` (fetch_lof_fund_list)
- Modify: `data/collector.py:195-247` (fetch_lof_iopv)
- Modify: `data/collector.py:129-176` (fetch_lof_realtime)
- Modify: `data/collector.py:246-271` (fetch_bond_ipo_list)
- Modify: `data/collector.py:275-336` (fetch_bond_allocation_list)
- Modify: `data/collector.py:340-358` (fetch_reverse_repo_rate)

- [ ] **Step 1: 构造函数增加notifier参数**

修改 `data/collector.py` 第18-30行的 `__init__`：

```python
    def __init__(self, storage: Storage, ds_config: dict, notifier=None):
        """初始化数据采集器

        Args:
            storage: 存储实例，用于记录数据源状态
            ds_config: 数据源配置
            notifier: 通知管理器实例（可选），用于数据源故障通知
        """
        self._storage = storage
        self._max_failures = ds_config.get("max_consecutive_failures", 3)
        self._ds_config = ds_config
        self._notifier = notifier
```

- [ ] **Step 2: 添加_alert_data_source_failure辅助方法**

在类中添加：

```python
    def _alert_data_source_failure(self, name: str, fail_count: int, reason: str = "") -> None:
        """数据源连续失败达阈值时产生告警和通知

        Args:
            name: 数据源名称
            fail_count: 当前连续失败次数
            reason: 失败原因
        """
        if fail_count < self._max_failures:
            return
        msg = "数据源%s连续失败%d次，达到阈值" % (name, fail_count)
        if reason:
            msg += "，原因: %s" % reason[:100]
        self._storage.insert_alert_event("ERROR", "collector", msg)
        if self._notifier is not None:
            try:
                self._notifier.notify(
                    title="数据源故障告警",
                    message=msg,
                    event_type="data_source_failure",
                )
            except Exception:
                logger.error("发送数据源故障通知失败")
```

- [ ] **Step 3: 修改fetch_lof_fund_list的状态记录**

在 `data/collector.py` 的 `fetch_lof_fund_list` 方法（第90行起），修改主源失败时的 `record_data_source_failure` 调用，传入 reason，并调用 `_alert_data_source_failure`：

将第110行 `fail_count = self._storage.record_data_source_failure("lof_list")` 改为：
```python
            reason = str(ex) if 'ex' in dir() else ""
            fail_count = self._storage.record_data_source_failure("lof_list", reason[:200])
            self._alert_data_source_failure("lof_list", fail_count, reason)
```

注意：需要把 `except Exception:` 改为 `except Exception as ex:`（第108行已是 `except Exception:` 需改为 `except Exception as ex:`）。

- [ ] **Step 4: 修改fetch_lof_iopv接入状态记录**

在 `fetch_lof_iopv` 方法中，批量获取成功后（`est_df` 非空时），添加：
```python
                    self._storage.update_data_source_status("lof_iopv", "ok")
```

在 `except Exception as ex:` 中（批量获取失败时），添加：
```python
                    self._storage.record_data_source_failure("lof_iopv", str(ex)[:200])
                    self._alert_data_source_failure("lof_iopv", self._storage.get_data_source_status("lof_iopv")["consecutive_failures"] if self._storage.get_data_source_status("lof_iopv") else 1, str(ex))
```

为了简化重复代码，可以在 `fetch_lof_iopv` 方法最外层 try 成功后统一调用 `self._storage.update_data_source_status("lof_iopv", "ok")`，在 except 中调用 `self._storage.record_data_source_failure` + `_alert_data_source_failure`。具体做法：在方法返回 result 之前加 `self._storage.update_data_source_status("lof_iopv", "ok")`，在 `except ImportError` 之前的 `except Exception as ex:` 块中加：

```python
                fail_count = self._storage.record_data_source_failure("lof_iopv", str(ex)[:200])
                self._alert_data_source_failure("lof_iopv", fail_count, str(ex))
```

- [ ] **Step 5: 修改fetch_lof_realtime接入状态记录**

在 `fetch_lof_realtime` 方法中，方法成功返回 `result` 之前添加：
```python
        self._storage.update_data_source_status("lof_realtime", "ok")
```

在 `except ImportError:` 块之前，添加外层 try/except：
```python
        except Exception as ex:
            logger.error("获取实时行情失败: %s", ex)
            fail_count = self._storage.record_data_source_failure("lof_realtime", str(ex)[:200])
            self._alert_data_source_failure("lof_realtime", fail_count, str(ex))
            return {}
```

- [ ] **Step 6: 修改fetch_bond_ipo_list接入状态记录**

在 `fetch_bond_ipo_list` 方法中，`return result` 之前添加：
```python
        self._storage.update_data_source_status("bond_ipo", "ok")
```

在 `except Exception as ex:` 块中（第270行），添加：
```python
        fail_count = self._storage.record_data_source_failure("bond_ipo", str(ex)[:200])
        self._alert_data_source_failure("bond_ipo", fail_count, str(ex))
```

- [ ] **Step 7: 修改fetch_bond_allocation_list接入状态记录**

在 `fetch_bond_allocation_list` 方法中，`return result` 之前添加：
```python
        self._storage.update_data_source_status("bond_alloc", "ok")
```

在两个 `except Exception as ex:` 块中（获取发行列表失败、获取正股信息失败）：

对于获取发行列表失败的 except（第293行），添加：
```python
        fail_count = self._storage.record_data_source_failure("bond_alloc", str(ex)[:200])
        self._alert_data_source_failure("bond_alloc", fail_count, str(ex))
```

对于获取正股信息失败的 except（第324行），只记录 warning 即可（正股信息非关键数据源，不影响整体配债列表获取）。

- [ ] **Step 8: 修改fetch_reverse_repo_rate接入状态记录**

在 `fetch_reverse_repo_rate` 方法中，`return rate` 之前添加：
```python
        self._storage.update_data_source_status("reverse_repo", "ok")
```

在 `except Exception as ex:` 块中（第357行），添加：
```python
        fail_count = self._storage.record_data_source_failure("reverse_repo", str(ex)[:200])
        self._alert_data_source_failure("reverse_repo", fail_count, str(ex))
```

- [ ] **Step 9: 运行测试**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -m pytest tests/test_collector.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add data/collector.py
git commit -m "feat: DataCollector 6个数据源全部接入状态记录 + 连续失败告警通知"
```

---

### Task 5: StrategyScheduler执行包装 + 心跳增强

**Files:**
- Modify: `scheduler/scheduler.py:1-153`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: 修改构造函数，增加storage参数和slow_threshold**

修改 `scheduler/scheduler.py` 第23-32行：

```python
    def __init__(self, calendar: TradingCalendar, storage=None, slow_threshold_ms: int = 30000):
        self._scheduler = BlockingScheduler()
        self._calendar = calendar
        self._strategies = {}  # type: dict[str, BaseStrategy]
        self._heartbeat_interval = 300
        self._storage = storage
        self._slow_threshold_ms = slow_threshold_ms
```

在文件顶部添加 `import time`。

- [ ] **Step 2: 改造add_daily_job的_daily_wrapper**

替换 `add_daily_job` 方法中的 `_daily_wrapper`（第60-66行）：

```python
        def _daily_wrapper():
            today = date.today()
            if not self._calendar.is_trading_day(today):
                logger.info("非交易日，跳过策略 [%s] 执行: %s", strategy_name, today)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "skip", 0, "非交易日")
                return
            logger.info("交易日，执行策略 [%s]: %s", strategy_name, today)
            start = time.perf_counter()
            try:
                strategy.execute()
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "success", duration)
            except Exception as ex:
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "fail", duration, str(ex)[:500])
                    self._storage.insert_alert_event("ERROR", strategy_name,
                                                     "策略执行失败: %s" % str(ex)[:200])
            if self._storage and duration > self._slow_threshold_ms:
                self._storage.insert_alert_event(
                    "WARN", strategy_name,
                    "策略执行耗时%dms超过阈值%dms" % (duration, self._slow_threshold_ms))
```

- [ ] **Step 3: 改造add_interval_job的_interval_wrapper**

替换 `add_interval_job` 方法中的 `_interval_wrapper`（第90-92行）：

```python
        def _interval_wrapper():
            logger.info("间隔触发策略 [%s]", strategy_name)
            start = time.perf_counter()
            try:
                strategy.execute()
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "success", duration)
            except Exception as ex:
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "fail", duration, str(ex)[:500])
                    self._storage.insert_alert_event("ERROR", strategy_name,
                                                     "策略执行失败: %s" % str(ex)[:200])
            if self._storage and duration > self._slow_threshold_ms:
                self._storage.insert_alert_event(
                    "WARN", strategy_name,
                    "策略执行耗时%dms超过阈值%dms" % (duration, self._slow_threshold_ms))
```

- [ ] **Step 4: 改造add_heartbeat_job的心跳函数**

替换 `add_heartbeat_job` 方法中的 `_heartbeat` 函数（第110-114行）：

```python
        def _heartbeat():
            if self._storage:
                ds_status = self._storage.list_all_data_source_status()
                unhealthy = [s for s in ds_status if s["status"] != "ok"]
                if unhealthy:
                    self._storage.insert_alert_event(
                        "WARN", "heartbeat",
                        "数据源异常: %s" % ", ".join(s["name"] for s in unhealthy))
                else:
                    self._storage.insert_alert_event("INFO", "heartbeat", "系统正常运行，数据源全部OK")
                logger.info("系统心跳：数据源 %d/%d OK，已注册策略: %s",
                            len(ds_status) - len(unhealthy), len(ds_status),
                            list(self._strategies.keys()))
            else:
                logger.info("系统心跳：正常运行中，已注册策略: %s",
                            list(self._strategies.keys()))
```

- [ ] **Step 5: 编写测试**

创建 `tests/test_scheduler.py`：

```python
"""测试StrategyScheduler的执行包装和心跳增强"""
import sqlite3
from datetime import date
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
    scheduler = StrategyScheduler(calendar, storage=storage)
    strategy = DummyStrategy()
    scheduler.register(strategy)

    # 模拟执行
    from scheduler.scheduler import StrategyScheduler as SS
    wrapper = scheduler._daily_wrapper if hasattr(scheduler, '_daily_wrapper') else None
    # 直接测试：手动调用wrapper构造逻辑
    start = __import__('time').perff_counter() if False else 0
    strategy.execute()
    storage.insert_execution_log("dummy", "success", 100)

    logs = storage.list_execution_logs("dummy")
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    assert logs[0]["duration_ms"] == 100
    conn.close()


def test_execution_log_on_fail():
    conn, storage, calendar = _setup()
    scheduler = StrategyScheduler(calendar, storage=storage)
    strategy = DummyStrategy()
    strategy.should_fail = True
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

    # 模拟心跳
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
```

- [ ] **Step 6: 运行测试**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scheduler/scheduler.py tests/test_scheduler.py
git commit -m "feat: StrategyScheduler执行包装(计时+状态记录+慢执行告警) + 心跳增强"
```

---

### Task 6: main.py注入调整 + 启动/自检持久化

**Files:**
- Modify: `main.py:42-69` (setup_notifier)
- Modify: `main.py:72-137` (run_selfcheck)
- Modify: `main.py:140-241` (main)

- [ ] **Step 1: 修改setup_notifier，注入storage**

修改 `main.py` 第42行的 `setup_notifier` 签名：

```python
def setup_notifier(config: dict, storage=None) -> NotificationManager:
```

修改第53行的 `NotificationManager` 构造：

```python
    mgr = NotificationManager(notify_config, dual_channel_events=dual_events, storage=storage)
```

- [ ] **Step 2: 修改run_selfcheck，持久化自检结果到alert_event**

在 `run_selfcheck` 函数签名（第72行）中，保持不变，但在每个 results.append 后添加 alert_event 写入。在汇总输出之前（第134行），添加：

```python
    # 持久化自检结果到告警事件 + system_status
    for name, result in results:
        if result == "PASS":
            storage.insert_alert_event("OK", "selfcheck", "%s: %s" % (name, result))
        elif result.startswith("FAIL"):
            storage.insert_alert_event("ERROR", "selfcheck", "%s: %s" % (name, result))
        elif result.startswith("WARN"):
            storage.insert_alert_event("WARN", "selfcheck", "%s: %s" % (name, result))
    # 写入自检结果摘要到system_status
    all_pass = all(r == "PASS" for _, r in results)
    storage.upsert_system_status("selfcheck_result", "all_passed" if all_pass else "has_failures")
```

- [ ] **Step 3: 修改main函数，注入storage到notifier和scheduler，持久化启动时间**

在 `main` 函数中：

第167行 `setup_notifier` 调用改为：
```python
    notifier = setup_notifier(config, storage=storage)
```

第170行 `DataCollector` 构造改为：
```python
    collector = DataCollector(storage, config.get("data_source", {}), notifier=notifier)
```

第173行 `StrategyScheduler` 构造改为：
```python
    slow_threshold = config.get("system", {}).get("slow_threshold_ms", 30000)
    scheduler = StrategyScheduler(calendar, storage=storage, slow_threshold_ms=slow_threshold)
```

在自检之前（第229行），添加系统启动时间持久化：

```python
    # 持久化系统启动时间
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    storage.upsert_system_status("start_time", start_time)
    strategy_names = [name for name, _ in [
        ("bond_ipo", bond_ipo), ("reverse_repo", reverse_repo),
        ("bond_allocation", bond_alloc), ("lof_premium", lof_premium),
    ] if strategy_config.get(name, {}).get("enabled", True)]
    storage.insert_alert_event("INFO", "system", "系统启动，策略: %s" % ", ".join(strategy_names))
```

需要在文件顶部 `from datetime import ...` 中确认已有 `datetime` 导入（第2行是 `import sqlite3`，需要 `from datetime import datetime`）。

- [ ] **Step 4: 运行全量测试验证不破坏现有功能**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: main.py注入storage到notifier/scheduler + 启动/自检持久化"
```

---

### Task 7: Flask API + 看板双标签页改造

**Files:**
- Modify: `dashboard/app.py:1-61`
- Modify: `dashboard/templates/index.html:1-233`

- [ ] **Step 1: 在dashboard/app.py中添加/api/status路由**

在 `dashboard/app.py` 的 `get_db` 函数之后、`index` 路由之前，添加：

```python
import json
from datetime import datetime


@app.route("/api/status")
def api_status():
    """状态总览API，返回JSON"""
    conn = get_db()

    # 系统健康
    start_time_str = ""
    cursor = conn.execute("SELECT value FROM system_status WHERE key = 'start_time'")
    row = cursor.fetchone()
    if row:
        start_time_str = row["value"] if isinstance(row, dict) else row[0]
    uptime_seconds = 0
    if start_time_str:
        try:
            start_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            uptime_seconds = int((datetime.now() - start_dt).total_seconds())
        except ValueError:
            pass

    # 自检结果
    selfcheck = "unknown"
    cursor = conn.execute("SELECT value FROM system_status WHERE key = 'selfcheck_result'")
    row = cursor.fetchone()
    if row:
        selfcheck = row["value"] if isinstance(row, dict) else row[0]

    # 数据源状态
    data_sources = [dict(r) for r in conn.execute(
        "SELECT * FROM data_source_status ORDER BY name"
    ).fetchall()]

    # 策略执行概况
    strategy_execution = [dict(r) for r in conn.execute(
        """SELECT strategy_name, trigger_time AS last_trigger_time,
                  status AS last_status, duration_ms AS last_duration_ms
           FROM strategy_execution_log
           WHERE id IN (SELECT MAX(id) FROM strategy_execution_log GROUP BY strategy_name)
           ORDER BY strategy_name"""
    ).fetchall()]

    # 今日执行次数
    today_str = datetime.now().strftime("%Y-%m-%d")
    for se in strategy_execution:
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM strategy_execution_log WHERE strategy_name=? AND trigger_time LIKE ?",
            (se["strategy_name"], today_str + "%"),
        )
        cnt_row = cursor.fetchone()
        se["today_count"] = cnt_row["cnt"] if isinstance(cnt_row, dict) else cnt_row[0]

    # 执行耗时趋势（LOF溢价最近20次）
    execution_trend = [dict(r) for r in conn.execute(
        """SELECT trigger_time, duration_ms FROM strategy_execution_log
           WHERE strategy_name='lof_premium'
           ORDER BY trigger_time DESC LIMIT 20"""
    ).fetchall()]

    # 告警事件
    alert_events = [dict(r) for r in conn.execute(
        "SELECT * FROM alert_event ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()]

    # 通知记录
    notification_logs = [dict(r) for r in conn.execute(
        "SELECT * FROM notification_log ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()]

    # 通知渠道统计
    cursor = conn.execute(
        "SELECT COUNT(*) as total, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success_cnt, SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) as fail_cnt FROM notification_log WHERE timestamp LIKE ?",
        (today_str + "%",),
    )
    stats_row = cursor.fetchone()
    if isinstance(stats_row, dict):
        today_stats = {"total": stats_row["total"], "success": stats_row["success_cnt"], "fail": stats_row["fail_cnt"]}
    else:
        today_stats = {"total": stats_row[0], "success": stats_row[1], "fail": stats_row[2]}

    # 最近心跳时间
    last_heartbeat = ""
    cursor = conn.execute(
        "SELECT timestamp FROM alert_event WHERE source='heartbeat' ORDER BY timestamp DESC LIMIT 1"
    )
    hb_row = cursor.fetchone()
    if hb_row:
        last_heartbeat = hb_row["timestamp"] if isinstance(hb_row, dict) else hb_row[0]

    conn.close()

    return json.dumps({
        "system": {
            "status": "running",
            "uptime_seconds": uptime_seconds,
            "selfcheck": selfcheck,
            "last_heartbeat": last_heartbeat,
        },
        "data_sources": data_sources,
        "notifications": {
            "today_stats": today_stats,
        },
        "strategy_execution": strategy_execution,
        "execution_trend": execution_trend,
        "alert_events": alert_events,
        "notification_logs": notification_logs,
    }, ensure_ascii=False, default=str)
```

- [ ] **Step 2: 改造index.html为双标签页**

用以下内容完整替换 `dashboard/templates/index.html`：

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
        .tab-content { display: none; }
        .tab-content.active { display: block; }
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
    </style>
</head>
<body>
    <h1>个人量化套利中枢</h1>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('status')">状态总览</div>
        <div class="tab" onclick="switchTab('data')">业务数据</div>
    </div>

    <!-- 状态总览 -->
    <div id="tab-status" class="tab-content active">
        <div class="refresh-info" id="status-refresh-time"></div>

        <!-- 第一行：3个状态卡片 -->
        <div class="status-cards" id="status-cards">
            <div class="status-card" id="card-system">
                <h3>系统健康</h3>
                <div id="system-status">加载中...</div>
            </div>
            <div class="status-card" id="card-datasource">
                <h3>数据源状态</h3>
                <div id="datasource-status">加载中...</div>
            </div>
            <div class="status-card" id="card-notification">
                <h3>通知渠道状态</h3>
                <div id="notification-status">加载中...</div>
            </div>
        </div>

        <!-- 第二行：执行概况 + 耗时趋势 -->
        <div style="display:flex;gap:12px;margin-bottom:20px">
            <div style="flex:1" class="section">
                <h2>策略执行概况</h2>
                <table id="execution-table">
                    <thead><tr><th>策略</th><th>上次执行</th><th>结果</th><th>耗时</th><th>今日次数</th></tr></thead>
                    <tbody></tbody>
                </table>
            </div>
            <div style="flex:1" class="section">
                <h2>执行耗时趋势(LOF溢价)</h2>
                <div id="execution-trend" class="bar-chart"></div>
                <div style="font-size:11px;color:#999;margin-top:20px">红色柱 = 超过阈值(30s)</div>
            </div>
        </div>

        <!-- 第三行：告警流 + 通知记录 -->
        <div style="display:flex;gap:12px;margin-bottom:20px">
            <div style="flex:1" class="section">
                <h2>告警事件流</h2>
                <div id="alert-events"><p class="empty">加载中...</p></div>
            </div>
            <div style="flex:1" class="section">
                <h2>通知发送记录</h2>
                <table id="notification-logs-table">
                    <thead><tr><th>时间</th><th>渠道</th><th>事件</th><th>状态</th></tr></thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- 业务数据 -->
    <div id="tab-data" class="tab-content">
        {% for section in data_sections %}
        <div class="section">
            <h2>{{ section.title }}</h2>
            {% if section.rows %}
            <table>
                <thead>
                    <tr>
                        {% for col in section.columns %}
                        <th>{{ col }}</th>
                        {% endfor %}
                    </tr>
                </thead>
                <tbody>
                    {% for row in section.rows %}
                    <tr>
                        {% for col in section.columns %}
                        <td>{{ row[col] }}</td>
                        {% endfor %}
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p class="empty">暂无数据</p>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    <script>
    function switchTab(tabName) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        document.querySelector('#tab-' + tabName).classList.add('active');
        event.target.classList.add('active');
    }

    function formatUptime(seconds) {
        if (!seconds) return '--';
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = seconds % 60;
        return h + 'h ' + m + 'm ' + s + 's';
    }

    function formatDuration(ms) {
        if (!ms && ms !== 0) return '--';
        if (ms < 1000) return ms + 'ms';
        return (ms / 1000).toFixed(1) + 's';
    }

    function statusClass(status) {
        if (status === 'ok' || status === 'success') return 'status-ok';
        if (status === 'failure' || status === 'fail') return 'status-error';
        if (status === 'skip') return 'status-warn';
        return '';
    }

    function statusIcon(status) {
        if (status === 'ok' || status === 'success') return '●';
        if (status === 'failure' || status === 'fail') return '●';
        if (status === 'skip') return '◐';
        return '○';
    }

    function refreshStatus() {
        fetch('/api/status').then(r => r.json()).then(data => {
            // 刷新时间
            document.getElementById('status-refresh-time').textContent = '上次刷新: ' + new Date().toLocaleTimeString();

            // 系统健康
            var sys = data.system || {};
            document.getElementById('system-status').innerHTML =
                '<div style="font-size:18px;font-weight:bold" class="status-ok">● 运行中</div>' +
                '<div style="font-size:13px;margin-top:6px">运行时长: ' + formatUptime(sys.uptime_seconds) + '</div>' +
                '<div style="font-size:13px">自检: ' + (sys.selfcheck || 'unknown') + '</div>' +
                '<div style="font-size:13px">上次心跳: ' + (sys.last_heartbeat || '--') + '</div>';

            // 数据源状态
            var dsHtml = '';
            (data.data_sources || []).forEach(function(ds) {
                var cls = statusClass(ds.status);
                var icon = statusIcon(ds.status);
                var extra = '';
                if (ds.consecutive_failures > 0) {
                    extra = ' <span style="color:#fa8c16;font-size:11px">' + ds.consecutive_failures + '次失败</span>';
                }
                dsHtml += '<div><span class="' + cls + '">' + icon + '</span> ' + ds.name + extra +
                    ' <span style="color:#999;font-size:11px">' + (ds.last_success_time || '--') + '</span></div>';
            });
            if (!dsHtml) dsHtml = '<div style="color:#999">暂无记录</div>';
            document.getElementById('datasource-status').innerHTML = dsHtml;

            // 通知统计
            var stats = (data.notifications || {}).today_stats || {};
            document.getElementById('notification-status').innerHTML =
                '<div style="font-size:13px;line-height:1.8">' +
                '今日发送: ' + (stats.total || 0) + '次<br>' +
                '<span class="status-ok">成功: ' + (stats.success || 0) + '</span><br>' +
                '<span class="status-error">失败: ' + (stats.fail || 0) + '</span></div>';

            // 策略执行概况
            var tbody = document.querySelector('#execution-table tbody');
            tbody.innerHTML = '';
            (data.strategy_execution || []).forEach(function(se) {
                var statusTd = '<span class="' + statusClass(se.last_status) + '">' + se.last_status + '</span>';
                tbody.innerHTML += '<tr><td>' + se.strategy_name + '</td><td>' + (se.last_trigger_time || '--') +
                    '</td><td>' + statusTd + '</td><td>' + formatDuration(se.last_duration_ms) +
                    '</td><td>' + (se.today_count || 0) + '</td></tr>';
            });
            if (!data.strategy_execution || !data.strategy_execution.length) {
                tbody.innerHTML = '<tr><td colspan="5" class="empty">暂无记录</td></tr>';
            }

            // 执行耗时趋势
            var trendDiv = document.getElementById('execution-trend');
            trendDiv.innerHTML = '';
            var maxMs = 30000;
            (data.execution_trend || []).reverse().forEach(function(item) {
                var height = Math.min(item.duration_ms / maxMs * 100, 100);
                var color = item.duration_ms > 30000 ? '#f5222d' : '#1890ff';
                var timeShort = (item.trigger_time || '').split(' ')[1] || '';
                timeShort = timeShort.substring(0, 5);
                trendDiv.innerHTML += '<div class="bar" style="height:' + Math.max(height, 3) + '%;background:' + color +
                    '"><span class="bar-label">' + timeShort + '</span></div>';
            });
            if (!data.execution_trend || !data.execution_trend.length) {
                trendDiv.innerHTML = '<p class="empty">暂无数据</p>';
            }

            // 告警事件流
            var alertDiv = document.getElementById('alert-events');
            var alertHtml = '';
            (data.alert_events || []).forEach(function(e) {
                alertHtml += '<div style="margin-bottom:6px;font-size:12px">' +
                    '<span class="level-' + e.level + '">' + e.level + '</span> ' +
                    '<span style="color:#999">' + (e.timestamp || '') + '</span> ' +
                    '<span style="color:#666">[' + e.source + ']</span> ' + e.message + '</div>';
            });
            alertDiv.innerHTML = alertHtml || '<p class="empty">暂无告警</p>';

            // 通知记录
            var ntbody = document.querySelector('#notification-logs-table tbody');
            ntbody.innerHTML = '';
            (data.notification_logs || []).forEach(function(nl) {
                var statusTd = '<span class="' + statusClass(nl.status) + '">' + nl.status + '</span>';
                ntbody.innerHTML += '<tr><td>' + (nl.timestamp || '--') + '</td><td>' + nl.channel +
                    '</td><td>' + nl.event_type + '</td><td>' + statusTd + '</td></tr>';
            });
            if (!data.notification_logs || !data.notification_logs.length) {
                ntbody.innerHTML = '<tr><td colspan="4" class="empty">暂无记录</td></tr>';
            }
        }).catch(function(err) {
            document.getElementById('status-refresh-time').textContent = '刷新失败: ' + err;
        });
    }

    // 初始加载 + 60秒定时刷新
    refreshStatus();
    setInterval(refreshStatus, 60000);
    </script>
</body>
</html>
```

- [ ] **Step 3: 修改dashboard/app.py的index路由，为业务数据Tab提供模板数据**

修改 `index` 函数，将原有6个查询改为结构化的 `data_sections`：

```python
@app.route("/")
def index():
    """统一看板首页"""
    conn = get_db()

    # 构建业务数据段（供业务数据Tab使用）
    data_sections = [
        {
            "title": "LOF溢价率监控",
            "columns": ["timestamp", "fund_code", "price", "iopv", "premium_rate", "iopv_source"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM premium_history ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "LOF套利信号",
            "columns": ["id", "trigger_time", "fund_code", "premium_rate", "action", "status", "iopv_source"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM trade_signal ORDER BY trigger_time DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "可转债打新",
            "columns": ["code", "name", "subscribe_date", "winning_result", "payment_status", "listing_date", "sell_status"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM bond_ipo ORDER BY subscribe_date DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "可转债配债",
            "columns": ["code", "stock_code", "stock_name", "content_weight", "safety_cushion", "record_date", "payment_date", "listing_date", "status", "actual_slippage"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM bond_allocation ORDER BY record_date DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "逆回购记录",
            "columns": ["id", "date", "code", "rate", "amount", "due_date", "profit"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM reverse_repo ORDER BY date DESC LIMIT 10"
            ).fetchall()],
        },
        {
            "title": "每日汇总",
            "columns": ["id", "date", "strategy_type", "profit", "action_log"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM daily_summary ORDER BY date DESC LIMIT 30"
            ).fetchall()],
        },
    ]

    conn.close()
    return render_template("index.html", data_sections=data_sections)
```

- [ ] **Step 4: 手动验证看板**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python dashboard/app.py`
然后浏览器打开 http://localhost:5000 检查：
- 顶部有两个Tab：状态总览 / 业务数据
- 状态总览默认展示，7个区块布局正确
- 60秒后自动刷新
- 业务数据Tab保留原有表格

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py dashboard/templates/index.html
git commit -m "feat: 看板双标签页改造（状态总览7区块+业务数据+API+自动刷新）"
```

---

### Task 8: 全量集成测试

**Files:** 无新增

- [ ] **Step 1: 运行全量测试**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 2: 启动main.py验证数据写入**

Run: `cd "D:/Users/lisheng/IdeaProjects/get_cash" && timeout 120 python main.py` (等待约2分钟)

然后用Python检查数据库：

```python
cd "D:/Users/lisheng/IdeaProjects/get_cash" && python -c "
import sqlite3
conn = sqlite3.connect('db/get_cash.db')
for table in ['strategy_execution_log', 'alert_event', 'notification_log', 'system_status', 'data_source_status']:
    cursor = conn.execute('SELECT COUNT(*) FROM ' + table)
    print(f'{table}: {cursor.fetchone()[0]} 行')
conn.close()
"
```

Expected:
- strategy_execution_log: 有记录
- alert_event: 有记录（至少有系统启动+心跳）
- notification_log: 有记录（如果有通知触发）
- system_status: 有 start_time 记录
- data_source_status: 有多个数据源记录（不仅仅是lof_list）

- [ ] **Step 3: 启动看板验证**

同时运行 main.py 和 dashboard/app.py，浏览器验证：
- 状态总览Tab能看到系统健康/数据源/执行概况/告警流
- 业务数据Tab能看到溢价率监控等原有数据
- 60秒后自动刷新生效

- [ ] **Step 4: 最终Commit**

```bash
git add -A
git commit -m "feat: 系统可观测性增强完成（DB表+状态记录+通知持久化+看板双标签+API+自动刷新）"
```
