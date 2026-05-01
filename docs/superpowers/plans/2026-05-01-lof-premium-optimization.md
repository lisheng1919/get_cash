# LOF溢价数据优化与数据源切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决LOF数据源不全（换东方财富）和溢价历史数据膨胀（降采样聚合+清理+分组展示）两个问题

**Architecture:** 数据源切换在 collector.py 内部完成，对外接口不变。降采样通过新增 premium_hourly 聚合表 + 定时聚合任务 + 每日清理任务实现。看板新增汇总API，前端改为基金分组视图+展开明细。

**Tech Stack:** Python 3.10, akshare, SQLite, APScheduler, Flask, Petite-Vue

---

## File Structure

| 文件 | 变更类型 | 职责 |
|------|---------|------|
| `data/collector.py` | 修改 | 主源从新浪切换到东方财富(fund_value_estimation_em)，备源改为新浪 |
| `data/models.py` | 修改 | 新增 premium_hourly 表DDL和索引 |
| `data/storage.py` | 修改 | 新增聚合/清理/查询方法 |
| `main.py` | 修改 | 注册每小时聚合任务和每日清理任务 |
| `dashboard/app.py` | 修改 | 新增汇总API，调整明细API |
| `dashboard/templates/index.html` | 修改 | LOF溢价历史改为分组视图+展开明细 |
| `tests/test_collector.py` | 修改 | 适配数据源切换 |
| `tests/test_storage_pagination.py` | 修改 | 新增聚合/清理测试 |
| `tests/test_dashboard_api.py` | 修改 | 新增汇总API测试 |

---

### Task 1: 数据源切换 — collector.py 主源从新浪换为东方财富

**Files:**
- Modify: `data/collector.py:54-108`
- Test: `tests/test_collector.py`

- [ ] **Step 1: 写主源切换的失败测试**

在 `tests/test_collector.py` 末尾追加：

```python
def test_fetch_lof_fund_list_primary_uses_eastmoney(monkeypatch):
    """验证主源使用fund_value_estimation_em获取LOF列表"""
    import pandas as pd
    from data.collector import DataCollector

    # mock fund_value_estimation_em 返回包含基金代码和名称的DataFrame
    mock_df = pd.DataFrame({
        "基金代码": ["164906", "501050"],
        "基金简称": ["交银互联网", "华夏上证50"],
        "估算值": [1.0, 2.0],
    })
    # 动态日期列名模拟
    mock_df.rename(columns={"估算值": "2026-05-01-估值数据-估算值"}, inplace=True)

    called = {"estimation": False, "sina": False}

    class FakeAk:
        @staticmethod
        def fund_value_estimation_em(symbol):
            called["estimation"] = True
            assert symbol == "LOF"
            return mock_df

        @staticmethod
        def fund_etf_category_sina(symbol):
            called["sina"] = True
            return pd.DataFrame()

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    collector = DataCollector(storage, {})

    monkeypatch.setattr("data.collector.ak", FakeAk())
    # 调用主源
    result = collector._fetch_lof_list_primary()

    assert called["estimation"] is True, "主源应调用fund_value_estimation_em"
    assert called["sina"] is False, "主源不应调用fund_etf_category_sina"
    assert len(result) >= 1, "应返回基金列表"
    conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_collector.py::test_fetch_lof_fund_list_primary_uses_eastmoney -v`
Expected: FAIL — 当前主源调用的是 `fund_etf_category_sina`

- [ ] **Step 3: 重写 `_fetch_lof_list_primary`**

将 `data/collector.py` 的 `_fetch_lof_list_primary` 方法替换为：

```python
    def _fetch_lof_list_primary(self) -> List[Dict]:
        """主源获取LOF基金列表（东方财富）

        使用akshare的fund_value_estimation_em接口获取全量LOF估值数据，
        同时提取基金列表和IOPV，一次请求覆盖所有LOF基金，比新浪更全。
        缓存IOPV数据供fetch_lof_iopv使用。

        Returns:
            LOF基金列表，每项包含 code, name, status, is_suspended, daily_volume
        """
        try:
            import akshare as ak
            df = ak.fund_value_estimation_em(symbol="LOF")
            if df is None or df.empty:
                logger.warning("东方财富LOF估值返回空数据")
                return []

            # 找到估值列（列名含动态日期前缀，如 "2026-05-01-估值数据-估算值"）
            est_col = None
            for col in df.columns:
                if "估算值" in str(col) and "单位净值" not in str(col):
                    est_col = col
                    break

            # 找到名称列
            name_col = None
            for col in df.columns:
                if "基金简称" in str(col):
                    name_col = col
                    break

            result = []
            # 缓存IOPV数据供fetch_lof_iopv使用
            self._lof_iopv_cache = {}
            for _, row in df.iterrows():
                code = str(row.get("基金代码", "")).strip()
                if not code:
                    continue
                name = str(row.get(name_col, "")).strip() if name_col else ""
                # 缓存IOPV
                iopv = 0.0
                if est_col:
                    val = row.get(est_col, 0)
                    if val and str(val).strip() not in ("", "---", "--"):
                        try:
                            iopv = float(val)
                            self._lof_iopv_cache[code] = iopv
                        except (ValueError, TypeError):
                            pass
                # 价格暂不从此接口获取，留空由fetch_lof_realtime补充
                result.append({
                    "code": code,
                    "name": name,
                    "status": "normal",
                    "is_suspended": False,
                    "daily_volume": 0.0,
                })
            return result
        except Exception as ex:
            logger.error("主源(东方财富)获取LOF基金列表失败: %s", ex)
            raise
```

- [ ] **Step 4: 将 `_fetch_lof_list_fallback` 改为调用新浪接口**

替换 `data/collector.py` 的 `_fetch_lof_list_fallback`：

```python
    def _fetch_lof_list_fallback(self) -> List[Dict]:
        """备用源获取LOF基金列表（新浪）

        东方财富主源失败时的备源，使用新浪分类接口。
        新浪覆盖可能不全，但作为降级方案可接受。

        Returns:
            LOF基金列表
        """
        try:
            import akshare as ak
            df = ak.fund_etf_category_sina(symbol="LOF基金")
            if df is None or df.empty:
                logger.warning("新浪备源返回空数据")
                return []

            result = []
            self._lof_price_cache = getattr(self, "_lof_price_cache", {})
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                if not code:
                    continue
                name = str(row.get("名称", "")).strip()
                amount = float(row.get("成交额", 0) or 0)
                daily_volume = amount / 10000.0
                price = float(row.get("最新价", 0) or 0)
                is_suspended = price <= 0
                if price > 0:
                    self._lof_price_cache[code] = price
                result.append({
                    "code": code,
                    "name": name,
                    "status": "normal",
                    "is_suspended": is_suspended,
                    "daily_volume": round(daily_volume, 2),
                })
            logger.info("新浪备源获取LOF基金列表成功，共%d条", len(result))
            return result
        except Exception as ex:
            logger.error("新浪备源获取LOF基金列表失败: %s", ex)
            return []
```

- [ ] **Step 5: 更新 `fetch_lof_iopv` 优先使用主源缓存的IOPV**

在 `fetch_lof_iopv` 方法中，批量获取逻辑之前增加主源缓存检查：

在 `if not codes:` 后、`result = {}` 后增加：

```python
        result = {}
        # 优先使用主源(fund_value_estimation_em)已缓存的IOPV
        cached_iopv = getattr(self, "_lof_iopv_cache", {})
        if cached_iopv:
            for code in codes:
                pure_code = self._strip_code_prefix(code)
                if pure_code in cached_iopv:
                    result[code] = {"iopv": cached_iopv[pure_code], "iopv_source": "estimated"}
```

同时将后续的批量获取逻辑改为仅处理 `missed_codes`：

在 `# 尝试批量获取LOF估值数据` 之前增加：

```python
        missed_codes = [c for c in codes if c not in result]
        if not missed_codes:
            self._storage.update_data_source_status("lof_iopv", "ok")
            return result
```

并将原批量获取逻辑中的 `for code in codes:` 改为 `for code in missed_codes:`，以及后续的 `missed_codes` 计算改为：

```python
        missed_codes = [c for c in missed_codes if c not in result]
```

- [ ] **Step 6: 运行全部collector测试**

Run: `python -m pytest tests/test_collector.py -v`
Expected: 全部PASS

- [ ] **Step 7: 运行全部测试确认无回归**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 8: 提交**

```bash
git add data/collector.py tests/test_collector.py
git commit -m "feat: LOF数据源从新浪切换到东方财富，备源改为新浪"
```

---

### Task 2: 新增 premium_hourly 聚合表

**Files:**
- Modify: `data/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 在 models.py 的 DDL_STATEMENTS 中新增 premium_hourly 表**

在 `premium_history` 表DDL之后追加：

```python
    # 溢价率小时聚合表
    """CREATE TABLE IF NOT EXISTS premium_hourly (
        fund_code TEXT NOT NULL DEFAULT '',
        hour TEXT NOT NULL DEFAULT '',
        avg_premium REAL NOT NULL DEFAULT 0.0,
        max_premium REAL NOT NULL DEFAULT 0.0,
        min_premium REAL NOT NULL DEFAULT 0.0,
        avg_price REAL NOT NULL DEFAULT 0.0,
        avg_iopv REAL NOT NULL DEFAULT 0.0,
        sample_count INT NOT NULL DEFAULT 0,
        threshold_count INT NOT NULL DEFAULT 0,
        create_time TEXT NOT NULL DEFAULT '',
        update_time TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (fund_code, hour)
    )""",
```

在 `INDEX_STATEMENTS` 中追加：

```python
    "CREATE INDEX IF NOT EXISTS idx_premium_hourly_hour ON premium_hourly(hour)",
```

同时在 `premium_history` 表中增加复合索引：

```python
    "CREATE INDEX IF NOT EXISTS idx_premium_history_code_ts ON premium_history(fund_code, timestamp)",
```

- [ ] **Step 2: 写测试验证新表创建**

在 `tests/test_models.py` 中追加：

```python
def test_init_db_creates_premium_hourly():
    """验证init_db创建premium_hourly表"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='premium_hourly'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_premium_hourly_composite_pk():
    """验证premium_hourly的复合主键(fund_code, hour)"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO premium_hourly (fund_code, hour, avg_premium, max_premium, min_premium, avg_price, avg_iopv, sample_count, threshold_count, create_time, update_time) "
        "VALUES ('164906', '2026-05-01 09', 3.0, 4.0, 2.0, 1.0, 1.0, 10, 2, '2026-05-01 10:05:00', '2026-05-01 10:05:00')"
    )
    # 同一fund_code+hour应冲突
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO premium_hourly (fund_code, hour, avg_premium, max_premium, min_premium, avg_price, avg_iopv, sample_count, threshold_count, create_time, update_time) "
            "VALUES ('164906', '2026-05-01 09', 2.5, 3.0, 2.0, 1.0, 1.0, 5, 1, '2026-05-01 10:10:00', '2026-05-01 10:10:00')"
        )
    conn.close()
```

- [ ] **Step 3: 运行测试**

Run: `python -m pytest tests/test_models.py -v`
Expected: 全部PASS

- [ ] **Step 4: 提交**

```bash
git add data/models.py tests/test_models.py
git commit -m "feat: 新增premium_hourly聚合表和复合索引"
```

---

### Task 3: Storage 新增聚合、清理、查询方法

**Files:**
- Modify: `data/storage.py`
- Test: `tests/test_storage_pagination.py`

- [ ] **Step 1: 写聚合方法的失败测试**

在 `tests/test_storage_pagination.py` 末尾追加：

```python
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
    # 再次写入同一fund_code+hour，应更新
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
    # 插入9点的3条记录
    for i in range(3):
        storage.insert_premium_history(
            f"2026-05-01 09:{i*20:02d}:00", "164906",
            1.0 + i * 0.01, 1.0, 2.0 + i, "estimated"
        )
    # 插入10点的1条记录
    storage.insert_premium_history(
        "2026-05-01 10:00:00", "164906", 1.0, 1.0, 3.0, "estimated"
    )

    # 聚合9点
    count = storage.aggregate_premium_hourly("2026-05-01 09", threshold=3.0)
    assert count == 1  # 一只基金被聚合

    # 验证聚合结果
    row = storage._conn.execute(
        "SELECT * FROM premium_hourly WHERE fund_code='164906' AND hour='2026-05-01 09'"
    ).fetchone()
    assert row is not None
    assert row["sample_count"] == 3
    assert row["avg_premium"] == 3.0  # (2+3+4)/3
    assert row["max_premium"] == 4.0
    assert row["min_premium"] == 2.0
    assert row["threshold_count"] == 1  # 只有1条(4.0)超过阈值3.0

    # 9点未超阈值的记录应被删除，超阈值的保留
    remaining = storage._conn.execute(
        "SELECT COUNT(*) as cnt FROM premium_history WHERE fund_code='164906' AND timestamp LIKE '2026-05-01 09%'"
    ).fetchone()["cnt"]
    # premium_rate 4.0 > 3.0 保留, 2.0和3.0删除
    assert remaining == 1
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
    # 插入一条过期记录
    storage.insert_premium_history(
        "2026-01-01 09:00:00", "164906", 1.0, 1.0, 3.0, "estimated"
    )
    storage.upsert_premium_hourly("164906", "2026-01-01 09", 3.0, 3.0, 3.0, 1.0, 1.0, 1, 1)

    # 清理90天前的数据（假设今天是2026-05-01，1月1日已过期）
    deleted = storage.cleanup_old_premium_data(retention_days=90, now_str="2026-05-01 00:00:00")
    assert deleted >= 1

    # 验证记录已删除
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_storage_pagination.py -v -k "premium_hourly or cleanup_old_premium"`
Expected: FAIL — 方法不存在

- [ ] **Step 3: 在 storage.py 中实现聚合/清理/查询方法**

在 `Storage` 类的 `# ==================== 重载信号 ====================` 之前追加：

```python
    # ==================== 溢价率聚合 ====================

    def upsert_premium_hourly(self, fund_code: str, hour: str,
                               avg_premium: float, max_premium: float, min_premium: float,
                               avg_price: float, avg_iopv: float,
                               sample_count: int, threshold_count: int) -> None:
        """插入或更新溢价率小时聚合记录"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute(
            """INSERT INTO premium_hourly (fund_code, hour, avg_premium, max_premium, min_premium,
                   avg_price, avg_iopv, sample_count, threshold_count, create_time, update_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fund_code, hour) DO UPDATE SET
                   avg_premium=excluded.avg_premium,
                   max_premium=excluded.max_premium,
                   min_premium=excluded.min_premium,
                   avg_price=excluded.avg_price,
                   avg_iopv=excluded.avg_iopv,
                   sample_count=excluded.sample_count,
                   threshold_count=excluded.threshold_count,
                   update_time=excluded.update_time""",
            (fund_code, hour, avg_premium, max_premium, min_premium,
             avg_price, avg_iopv, sample_count, threshold_count, now, now),
        )
        self._conn.commit()

    def aggregate_premium_hourly(self, hour: str, threshold: float = 3.0) -> int:
        """聚合指定小时的premium_history数据到premium_hourly

        聚合后删除未超阈值的原始记录，保留超阈值的记录。

        Args:
            hour: 小时窗口，如 "2026-05-01 09"
            threshold: 溢价率阈值，绝对值超过此值的记录保留

        Returns:
            聚合的基金数量
        """
        hour_prefix = hour + "%"
        # 按 fund_code 分组聚合
        rows = self._conn.execute(
            "SELECT fund_code, "
            "AVG(premium_rate) as avg_premium, "
            "MAX(premium_rate) as max_premium, "
            "MIN(premium_rate) as min_premium, "
            "AVG(price) as avg_price, "
            "AVG(iopv) as avg_iopv, "
            "COUNT(*) as sample_count, "
            "SUM(CASE WHEN ABS(premium_rate) >= ? THEN 1 ELSE 0 END) as threshold_count "
            "FROM premium_history WHERE timestamp LIKE ? "
            "GROUP BY fund_code",
            (threshold, hour_prefix),
        ).fetchall()

        if not rows:
            return 0

        for row in rows:
            self.upsert_premium_hourly(
                fund_code=row["fund_code"],
                hour=hour,
                avg_premium=round(row["avg_premium"], 4),
                max_premium=round(row["max_premium"], 4),
                min_premium=round(row["min_premium"], 4),
                avg_price=round(row["avg_price"], 4),
                avg_iopv=round(row["avg_iopv"], 4),
                sample_count=row["sample_count"],
                threshold_count=row["threshold_count"],
            )

        # 删除已聚合的未超阈值记录（超阈值的保留供明细查看）
        self._conn.execute(
            "DELETE FROM premium_history WHERE timestamp LIKE ? AND ABS(premium_rate) < ?",
            (hour_prefix, threshold),
        )
        self._conn.commit()
        return len(rows)

    def cleanup_old_premium_data(self, retention_days: int, now_str: str = "") -> int:
        """清理超过保留期的溢价历史数据

        Args:
            retention_days: 保留天数
            now_str: 当前时间字符串，为空则使用datetime.now()

        Returns:
            删除的总记录数
        """
        if not now_str:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 计算截止日期
        from datetime import timedelta
        cutoff = (datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S") - timedelta(days=retention_days))
        cutoff_str = cutoff.strftime("%Y-%m-%d 00:00:00")
        cutoff_hour = cutoff.strftime("%Y-%m-%d %H")

        # 删除 premium_history
        cur1 = self._conn.execute(
            "DELETE FROM premium_history WHERE timestamp < ?", (cutoff_str,)
        )
        # 删除 premium_hourly
        cur2 = self._conn.execute(
            "DELETE FROM premium_hourly WHERE hour < ?", (cutoff_hour,)
        )
        self._conn.commit()
        return cur1.rowcount + cur2.rowcount
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_storage_pagination.py -v -k "premium_hourly or cleanup_old_premium"`
Expected: 全部PASS

- [ ] **Step 5: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 6: 提交**

```bash
git add data/storage.py tests/test_storage_pagination.py
git commit -m "feat: Storage新增premium_hourly聚合/清理/查询方法"
```

---

### Task 4: main.py 注册聚合和清理定时任务

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 在 main.py 的调度器启动前注册聚合任务**

在 `scheduler.add_config_poll_job(config_manager, interval=30)` 之后、静默过期清理之前追加：

```python
    # 溢价历史每小时聚合（每小时的第5分钟执行，聚合上一小时的数据）
    def aggregate_premium():
        from datetime import datetime, timedelta
        now = datetime.now()
        # 聚合上一个小时的数据
        last_hour = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H")
        lof_config = config.get("lof_premium", {})
        threshold = lof_config.get("premium_threshold", 3.0)
        count = storage.aggregate_premium_hourly(last_hour, threshold=threshold)
        if count > 0:
            logger.info("溢价历史聚合完成: %s, %d只基金", last_hour, count)

    scheduler._scheduler.add_job(
        aggregate_premium, 'cron', minute=5, id='aggregate_premium'
    )

    # 每日数据清理（凌晨2:00执行）
    def cleanup_premium_data():
        retention_days = int(config.get("system", {}).get("data_retention_days", 90))
        deleted = storage.cleanup_old_premium_data(retention_days=retention_days)
        if deleted > 0:
            logger.info("清理过期溢价数据: 删除%d条记录, 保留%d天", deleted, retention_days)
        # 每周VACUUM
        do_vacuum = config.get("system", {}).get("db_vacuum_weekly", True)
        if do_vacuum:
            import time
            # 周日执行VACUUM
            if datetime.now().weekday() == 6:
                conn.execute("VACUUM")
                logger.info("SQLite VACUUM完成")

    scheduler._scheduler.add_job(
        cleanup_premium_data, 'cron', hour=2, minute=0, id='cleanup_premium_data'
    )
```

需要在文件顶部确认 `datetime` 已导入（已有 `from datetime import datetime`）。

- [ ] **Step 2: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 3: 提交**

```bash
git add main.py
git commit -m "feat: 注册每小时溢价聚合任务和每日数据清理任务"
```

---

### Task 5: 看板新增汇总API + 调整明细API

**Files:**
- Modify: `dashboard/app.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: 在 app.py 新增 /api/data/lof_premium_summary 路由**

在 `api_data_lof_premium` 路由之后追加：

```python
    @app.route("/api/data/lof_premium_summary")
    def api_data_lof_premium_summary():
        """LOF溢价分组汇总 - 按基金分组显示小时级汇总"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        fund_code = request.args.get("fund_code")

        if fund_code:
            # 查询指定基金的小时汇总历史
            return jsonify(storage.query_paginated(
                "premium_hourly",
                page=page, page_size=page_size,
                search=search, search_columns=["fund_code"],
                order_by="hour", order_dir="DESC",
                extra_where="fund_code = ?",
                extra_params=[fund_code],
            ))
        else:
            # 查询所有基金的最新汇总（每只基金取最新一小时）
            where_clauses = []
            params = []
            if search:
                like_val = f"%{search}%"
                where_clauses.append("(ph.fund_code LIKE ? OR f.name LIKE ?)")
                params.extend([like_val, like_val])

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # 子查询：每只基金最新的一条hourly记录
            subquery = (
                "SELECT fund_code, MAX(hour) as latest_hour "
                "FROM premium_hourly GROUP BY fund_code"
            )
            count_sql = f"SELECT COUNT(*) as cnt FROM ({subquery}) sub{where_sql.replace('ph.', 'sub.')}"
            # 简化：直接查premium_hourly + lof_fund JOIN
            return jsonify(storage.query_paginated(
                "premium_hourly",
                page=page, page_size=page_size,
                search=search, search_columns=["fund_code"],
                order_by="hour", order_dir="DESC",
                join_clause="LEFT JOIN lof_fund f ON premium_hourly.fund_code = f.code",
                extra_select=", f.name as fund_name",
            ))
```

- [ ] **Step 2: 调整 /api/data/lof_premium 为超阈值明细查询**

将 `api_data_lof_premium` 路由修改为：

```python
    @app.route("/api/data/lof_premium")
    def api_data_lof_premium():
        """LOF溢价超阈值明细 - 按基金分页"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "timestamp")
        sort_order = request.args.get("sort_order", "DESC")
        fund_code = request.args.get("fund_code")

        extra_where = None
        extra_params = None
        search_cols = ["ph.fund_code", "ph.iopv_source", "f.name"]

        if fund_code:
            extra_where = "ph.fund_code = ?"
            extra_params = [fund_code]

        return jsonify(storage.query_paginated(
            "premium_history",
            page=page, page_size=page_size,
            search=search, search_columns=search_cols,
            order_by=sort_by, order_dir=sort_order,
            join_clause="LEFT JOIN lof_fund f ON ph.fund_code = f.code",
            extra_select=", f.name as fund_name",
            alias_prefix="ph",
            extra_where=extra_where,
            extra_params=extra_params,
        ))
```

- [ ] **Step 3: 写汇总API的测试**

在 `tests/test_dashboard_api.py` 末尾追加：

```python
def test_api_data_lof_premium_summary(app_client):
    """验证LOF溢价分组汇总API"""
    resp = app_client.get("/api/data/lof_premium_summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data


def test_api_data_lof_premium_with_fund_code(app_client):
    """验证LOF溢价明细API支持fund_code过滤"""
    resp = app_client.get("/api/data/lof_premium?fund_code=164906")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_dashboard_api.py -v`
Expected: 全部PASS

- [ ] **Step 5: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 6: 提交**

```bash
git add dashboard/app.py tests/test_dashboard_api.py
git commit -m "feat: 新增LOF溢价分组汇总API，调整明细API支持fund_code过滤"
```

---

### Task 6: 前端LOF溢价历史改为分组视图+展开明细

**Files:**
- Modify: `dashboard/templates/index.html`

- [ ] **Step 1: 将LOF溢价历史的 DataTable 改为分组汇总视图**

将 LOF溢价历史 section 的 DataTable 替换为自定义的分组视图：

```html
            <!-- LOF溢价历史（分组汇总视图） -->
            <div class="section">
                <h2>LOF溢价历史</h2>
                <div v-scope="LofPremiumSummary()" @vue:mounted="lofInit">
                    <div class="dt-toolbar">
                        <div class="dt-search">
                            <input type="text" v-model="search" placeholder="搜索基金代码/名称..." @keydown.enter="doSearch" @input="onSearchInput">
                            <button @click="doSearch">搜索</button>
                        </div>
                        <div class="dt-pagesize">
                            每页
                            <select :value="pageSize" @change="changePageSize($event.target.value)">
                                <option value="10">10</option>
                                <option value="20">20</option>
                                <option value="50">50</option>
                            </select>
                            条
                        </div>
                    </div>
                    <div v-if="loading" class="dt-loading">加载中...</div>
                    <table v-if="!loading">
                        <thead>
                            <tr>
                                <th style="width:30px"></th>
                                <th @click="toggleSort('fund_code')" :style="sortBy==='fund_code'?'cursor:pointer;font-weight:bold':'cursor:pointer'">基金代码 <span v-if="sortBy==='fund_code'">{{ sortDir==='ASC'?'↑':'↓' }}</span></th>
                                <th>基金名称</th>
                                <th @click="toggleSort('avg_premium')" :style="sortBy==='avg_premium'?'cursor:pointer;font-weight:bold':'cursor:pointer'">最新溢价率 <span v-if="sortBy==='avg_premium'">{{ sortDir==='ASC'?'↑':'↓' }}</span></th>
                                <th>最大溢价率</th>
                                <th>采样次数</th>
                                <th>超阈值次数</th>
                                <th @click="toggleSort('hour')" :style="sortBy==='hour'?'cursor:pointer;font-weight:bold':'cursor:pointer'">最近时间 <span v-if="sortBy==='hour'">{{ sortDir==='ASC'?'↑':'↓' }}</span></th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-if="items.length === 0"><td colspan="8" class="empty">暂无数据</td></tr>
                            <template v-for="item in items">
                                <tr style="cursor:pointer" @click="toggleExpand(item.fund_code)">
                                    <td>{{ expandedFund === item.fund_code ? '▼' : '▶' }}</td>
                                    <td>{{ item.fund_code }}</td>
                                    <td>{{ item.fund_name || '' }}</td>
                                    <td :class="statusClass(item.avg_premium >= 3 ? 'ok' : '')">{{ item.avg_premium ? item.avg_premium.toFixed(2) + '%' : '--' }}</td>
                                    <td>{{ item.max_premium ? item.max_premium.toFixed(2) + '%' : '--' }}</td>
                                    <td>{{ item.sample_count }}</td>
                                    <td>{{ item.threshold_count }}</td>
                                    <td>{{ item.hour }}</td>
                                </tr>
                                <tr v-if="expandedFund === item.fund_code">
                                    <td colspan="8" style="padding:8px 16px;background:#fafbfc">
                                        <div v-if="detailLoading" class="dt-loading">加载明细...</div>
                                        <table v-if="!detailLoading" style="width:100%;font-size:12px">
                                            <thead><tr><th>时间</th><th>价格</th><th>IOPV</th><th>溢价率</th><th>来源</th></tr></thead>
                                            <tbody>
                                                <tr v-if="detailItems.length === 0"><td colspan="5" class="empty">无超阈值记录</td></tr>
                                                <tr v-for="d in detailItems">
                                                    <td>{{ d.timestamp }}</td>
                                                    <td>{{ d.price }}</td>
                                                    <td>{{ d.iopv }}</td>
                                                    <td :class="statusClass('ok')">{{ d.premium_rate ? d.premium_rate.toFixed(2) + '%' : '--' }}</td>
                                                    <td>{{ d.iopv_source }}</td>
                                                </tr>
                                            </tbody>
                                        </table>
                                        <div v-if="detailItems.length > 0" style="margin-top:4px;font-size:11px;color:#1890ff;cursor:pointer" @click.stop="loadHistory(item.fund_code)">查看7天历史趋势 →</div>
                                    </td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                    <div class="dt-pagination" v-if="total > 0">
                        <span>共 {{ total }} 条，第 {{ page }}/{{ totalPages }} 页</span>
                        <div class="dt-page-btns">
                            <button :disabled="page <= 1" @click="changePage(1)">首页</button>
                            <button :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
                            <button :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
                            <button :disabled="page >= totalPages" @click="changePage(totalPages)">末页</button>
                        </div>
                    </div>
                </div>
            </div>
```

- [ ] **Step 2: 在 script 中新增 LofPremiumSummary 组件**

在 `/* ===== App 组件 ===== */` 之前追加：

```javascript
    /* ===== LOF溢价分组汇总组件 ===== */
    function LofPremiumSummary() {
        return {
            items: [],
            total: 0,
            page: 1,
            pageSize: 10,
            totalPages: 0,
            search: '',
            loading: false,
            sortBy: 'hour',
            sortDir: 'DESC',
            expandedFund: '',
            detailItems: [],
            detailLoading: false,

            lofInit() {
                this.fetchData();
            },

            fetchData() {
                var self = this;
                self.loading = true;
                var params = new URLSearchParams({
                    page: self.page,
                    page_size: self.pageSize,
                    sort_by: self.sortBy,
                    sort_order: self.sortDir
                });
                if (self.search) params.set('search', self.search);

                fetch('/api/data/lof_premium_summary?' + params.toString())
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        self.items = data.items || [];
                        self.total = data.total || 0;
                        self.page = data.page || 1;
                        self.pageSize = data.page_size || 10;
                        self.totalPages = data.total_pages || 0;
                        self.loading = false;
                    })
                    .catch(function() {
                        self.items = [];
                        self.total = 0;
                        self.totalPages = 0;
                        self.loading = false;
                    });
            },

            doSearch() {
                this.page = 1;
                this.fetchData();
            },

            onSearchInput() {
                if (!this.search) this.doSearch();
            },

            changePage(n) {
                if (n < 1 || n > this.totalPages) return;
                this.page = n;
                this.fetchData();
            },

            changePageSize(s) {
                this.pageSize = parseInt(s);
                this.page = 1;
                this.fetchData();
            },

            toggleSort(key) {
                if (this.sortBy === key) {
                    this.sortDir = this.sortDir === 'ASC' ? 'DESC' : 'ASC';
                } else {
                    this.sortBy = key;
                    this.sortDir = 'DESC';
                }
                this.page = 1;
                this.fetchData();
            },

            toggleExpand(fundCode) {
                if (this.expandedFund === fundCode) {
                    this.expandedFund = '';
                    this.detailItems = [];
                    return;
                }
                this.expandedFund = fundCode;
                this.detailLoading = true;
                this.detailItems = [];
                var self = this;
                fetch('/api/data/lof_premium?fund_code=' + fundCode + '&page_size=20&sort_by=timestamp&sort_order=DESC')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        self.detailItems = data.items || [];
                        self.detailLoading = false;
                    })
                    .catch(function() {
                        self.detailItems = [];
                        self.detailLoading = false;
                    });
            },

            loadHistory(fundCode) {
                // 跳转到7天历史趋势（可后续扩展为图表）
                var url = '/api/data/lof_premium_summary?fund_code=' + fundCode + '&page_size=168';
                var self = this;
                fetch(url)
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.items && data.items.length > 0) {
                            self.detailItems = [];
                            self.detailLoading = true;
                            // 将hourly数据映射为明细格式展示
                            var hourlyItems = data.items.map(function(h) {
                                return {
                                    timestamp: h.hour + ':00',
                                    price: h.avg_price ? h.avg_price.toFixed(4) : '--',
                                    iopv: h.avg_iopv ? h.avg_iopv.toFixed(4) : '--',
                                    premium_rate: h.avg_premium,
                                    iopv_source: '小时汇总(' + h.sample_count + '次采样)'
                                };
                            });
                            self.detailItems = hourlyItems;
                            self.detailLoading = false;
                        }
                    });
            }
        };
    }
```

- [ ] **Step 3: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 4: 提交**

```bash
git add dashboard/templates/index.html
git commit -m "feat: LOF溢价历史改为基金分组视图+展开超阈值明细"
```

---

### Task 7: 整体验证

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 2: 提交最终状态（如有遗漏修复）**

```bash
git add -A
git commit -m "chore: LOF溢价数据优化完成"
```

---

## Spec Coverage Check

| Spec 需求 | 对应 Task |
|-----------|----------|
| 数据源切换（东方财富主源+新浪备源） | Task 1 |
| premium_hourly 聚合表 | Task 2 |
| Storage 聚合/清理/查询方法 | Task 3 |
| 每小时聚合定时任务 | Task 4 |
| 每日清理+VACUUM定时任务 | Task 4 |
| LOF溢价分组汇总API | Task 5 |
| LOF溢价明细API调整(fund_code过滤) | Task 5 |
| 看板分组视图+展开明细 | Task 6 |
