# Bug修复与功能增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复已确认的P0/P1级Bug、前端Bug，增强搜索功能和安全脱敏，增加实用UI功能

**Architecture:** 按优先级分6个Task，P0 Bug优先修复，其余Task相互独立可并行。每个Task包含测试优先(TDD)的完整步骤。跳过API鉴权（本地单机系统过度设计）和RiskChecker日期重置（死代码未接入main.py）。

**Tech Stack:** Python 3.10, SQLite, Flask, Petite-Vue, unittest/pytest

---

## File Structure

| 文件 | 变更类型 | 职责 |
|------|---------|------|
| `data/storage.py` | 修改 | query_paginated 增加白名单校验 |
| `config_manager.py` | 修改 | init_from_yaml 逐分类检查逻辑 |
| `strategies/lof_premium/filter.py` | 修改 | 属性名 min_volume → _min_volume |
| `strategies/reverse_repo.py` | 修改 | _today 每次execute重新获取 |
| `main.py` | 修改 | SQLite WAL模式 + 静默过期清理定时任务 |
| `dashboard/app.py` | 修改 | days参数校验 + 搜索增强 + 敏感配置脱敏 + 日期范围查询 + 静默过期清理 |
| `dashboard/templates/index.html` | 修改 | statusClass修复 + 分页空数据 + 配置保存提示消失 + 搜索框清空 + 表头排序 + 刷新按钮 + password输入框 |
| `tests/test_storage_pagination.py` | 修改 | 增加白名单校验测试 |
| `tests/test_config_manager.py` | 修改 | 增加逐分类初始化测试 |
| `tests/test_filter.py` | 修改 | 增加属性名一致性测试 |
| `tests/test_reverse_repo.py` | 修改 | 增加_today跨天测试 |
| `tests/test_dashboard_api.py` | 修改 | 增加days校验/脱敏/搜索测试 |

---

### Task 1: P0 Bug — query_paginated SQL注入白名单校验

**Files:**
- Modify: `data/storage.py:505-538`
- Test: `tests/test_storage_pagination.py`

- [ ] **Step 1: 写白名单校验的失败测试**

在 `tests/test_storage_pagination.py` 末尾追加：

```python
import pytest

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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_storage_pagination.py -v -k "rejects_invalid or accepts_valid_params"`
Expected: 4个reject测试FAIL（ValueError未抛出），1个accept测试PASS

- [ ] **Step 3: 在 storage.py 中实现白名单校验**

在 `Storage` 类上方添加辅助函数，在 `query_paginated` 方法开头调用：

```python
import re

def _is_valid_identifier(name: str) -> bool:
    """校验是否为合法SQL标识符（仅含字母数字下划线，不以数字开头）"""
    return bool(re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name))
```

在 `query_paginated` 方法体最开头（`where_clauses = []` 之前）增加：

```python
        # 白名单校验，防止SQL注入
        if not _is_valid_identifier(table):
            raise ValueError(f"Invalid table name: {table}")
        if not _is_valid_identifier(order_by):
            raise ValueError(f"Invalid order_by: {order_by}")
        if order_dir.upper() not in ("ASC", "DESC"):
            raise ValueError(f"Invalid order_dir: {order_dir}, only ASC/DESC allowed")
        if search_columns:
            for col in search_columns:
                if not _is_valid_identifier(col):
                    raise ValueError(f"Invalid column name: {col}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_storage_pagination.py -v`
Expected: 全部PASS

- [ ] **Step 5: 提交**

```bash
git add data/storage.py tests/test_storage_pagination.py
git commit -m "fix: query_paginated增加白名单校验防止SQL注入"
```

---

### Task 2: P0 Bug — init_from_yaml 逐分类检查

**Files:**
- Modify: `config_manager.py:461-495`
- Test: `tests/test_config_manager.py`

- [ ] **Step 1: 写逐分类初始化的失败测试**

在 `tests/test_config_manager.py` 的 `TestConfigManager` 类中追加：

```python
    def test_init_from_yaml_per_category_skip(self):
        """验证init_from_yaml逐分类检查，只跳过已有数据的分类"""
        conn, storage, manager, _ = _create_env()
        try:
            # 只手动写入strategy分类的配置
            storage.upsert_config_kv("strategy", "bond_ipo", "enabled", "1", "bool", "启用策略", "")

            # 执行初始化
            manager.init_from_yaml()

            # strategy分类应跳过（已有数据），不会覆盖
            strategy_items = storage.get_config_by_category("strategy")
            # 只有人工写入的1条，不应有其他
            bond_ipo_enabled = storage.get_config_kv("strategy", "bond_ipo", "enabled")
            self.assertEqual(bond_ipo_enabled["value"], "1")

            # notify/risk/system分类应正常写入
            notify_items = storage.get_config_by_category("notify")
            self.assertGreater(len(notify_items), 0)
            risk_items = storage.get_config_by_category("risk")
            self.assertGreater(len(risk_items), 0)
            system_items = storage.get_config_by_category("system")
            self.assertGreater(len(system_items), 0)
        finally:
            conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_config_manager.py::TestConfigManager::test_init_from_yaml_per_category_skip -v`
Expected: FAIL — notify/risk/system分类为空，因为当前逻辑遇到strategy有数据就直接return了

- [ ] **Step 3: 修改 init_from_yaml 逻辑**

将 `config_manager.py` 的 `init_from_yaml` 方法中 for 循环的 `return` 改为 `continue`，并在写入循环中跳过已有数据的分类：

```python
    def init_from_yaml(self) -> None:
        """从config.yaml初始化配置到DB

        仅当DB中config_kv表对应分类为空时执行写入，避免覆盖用户修改。
        逐分类检查：只跳过已有数据的分类，其他分类正常初始化。
        """
        # 收集已有数据的分类
        populated_categories = set()
        for category in CONFIG_META:
            existing = self._storage.get_config_by_category(category)
            if existing:
                populated_categories.add(category)
                logger.info("DB已有配置(category=%s, %d条)，跳过该分类", category, len(existing))

        # 遍历CONFIG_META写入，跳过已有数据的分类
        count = 0
        for category, sections in CONFIG_META.items():
            if category in populated_categories:
                continue
            for section, keys in sections.items():
                for key, meta in keys.items():
                    value = self._get_yaml_value(
                        category, section, key, meta["default"]
                    )
                    value_str = _value_to_str(value, meta["value_type"])
                    self._storage.upsert_config_kv(
                        category=category,
                        section=section,
                        key=key,
                        value=value_str,
                        value_type=meta["value_type"],
                        label=meta["label"],
                        description=meta["description"],
                    )
                    count += 1

        if count > 0:
            logger.info("从config.yaml初始化配置完成，共写入%d条", count)
        else:
            logger.info("所有分类已有配置，跳过初始化")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_config_manager.py -v`
Expected: 全部PASS（包括原有的test_init_from_yaml_idempotent）

- [ ] **Step 5: 提交**

```bash
git add config_manager.py tests/test_config_manager.py
git commit -m "fix: init_from_yaml逐分类检查，不再整体跳过"
```

---

### Task 3: P0 Bug — LofFilter 属性名不一致

**Files:**
- Modify: `strategies/lof_premium/filter.py:11-27`
- Test: `tests/test_filter.py`

- [ ] **Step 1: 写属性名一致性测试**

在 `tests/test_filter.py` 末尾追加：

```python
def test_filter_attribute_name_matches_sub_obj_map():
    """LofFilter的属性名必须与STRATEGY_SUB_OBJ_MAP中映射一致"""
    from config_manager import STRATEGY_SUB_OBJ_MAP
    # STRATEGY_SUB_OBJ_MAP中lof_premium._filter映射了_min_volume
    filter_attrs = STRATEGY_SUB_OBJ_MAP["lof_premium"]["_filter"]
    assert "_min_volume" in filter_attrs
    # LofFilter实例应有_min_volume属性
    f = LofFilter(min_volume=500)
    assert hasattr(f, "_min_volume"), "LofFilter must have _min_volume attribute"
    assert f._min_volume == 500
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_filter.py::test_filter_attribute_name_matches_sub_obj_map -v`
Expected: FAIL — LofFilter只有 `min_volume` 没有 `_min_volume`

- [ ] **Step 3: 修改 LofFilter 属性名**

将 `strategies/lof_premium/filter.py` 中的 `self.min_volume` 改为 `self._min_volume`，同时更新引用：

```python
class LofFilter:
    """LOF基金过滤器

    根据成交量和停牌状态过滤不符合条件的基金。
    """

    def __init__(self, min_volume=500.0):
        """
        Args:
            min_volume: 最低日成交量（万元），低于此值的基金被过滤
        """
        self._min_volume = min_volume

    def filter_by_volume(self, daily_volume):
        """按成交量过滤"""
        return daily_volume >= self._min_volume

    def filter_by_suspension(self, is_suspended):
        """按停牌状态过滤"""
        return not is_suspended
```

- [ ] **Step 4: 运行全部filter测试确认通过**

Run: `python -m pytest tests/test_filter.py -v`
Expected: 全部PASS

- [ ] **Step 5: 确认热加载测试也通过**

Run: `python -m pytest tests/test_config_manager.py::TestConfigManager::test_reload_updates_strategy -v`
Expected: PASS — FakeLofFilter已有 `_min_volume` 属性

- [ ] **Step 6: 提交**

```bash
git add strategies/lof_premium/filter.py tests/test_filter.py
git commit -m "fix: LofFilter属性名min_volume改为_min_volume与映射一致"
```

---

### Task 4: P1 Bug — SQLite WAL模式 + 静默过期清理 + 逆回购_today + days校验

**Files:**
- Modify: `main.py:32-43`
- Modify: `strategies/reverse_repo.py:41,82-94`
- Modify: `dashboard/app.py:280-297`
- Test: `tests/test_reverse_repo.py`, `tests/test_dashboard_api.py`

- [ ] **Step 1: 写逆回购_today跨天测试**

在 `tests/test_reverse_repo.py` 末尾追加：

```python
def test_reverse_repo_today_updates_on_execute():
    """验证execute方法中_today会重新获取当天日期，不依赖构造时的固定值"""
    calendar = TradingCalendar()
    calendar.add_pre_holiday(date(2026, 9, 30), "国庆节前")
    strategy = _create_strategy(calendar=calendar)
    # 构造时设置一个旧日期
    strategy._today = date(2026, 1, 1)
    # execute时应重新获取date.today()
    strategy.execute()
    # 非节前日，不应通知。关键验证：_today被更新了
    from unittest.mock import patch
    with patch('strategies.reverse_repo.date') as mock_date:
        mock_date.today.return_value = date(2026, 9, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        strategy.execute()
        strategy._notifier.notify.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_reverse_repo.py::test_reverse_repo_today_updates_on_execute -v`
Expected: FAIL — `_today` 仍是构造时固定的值

- [ ] **Step 3: 修改 reverse_repo.py 的 execute 方法**

将 `strategies/reverse_repo.py` 的 `execute` 方法开头增加 `_today` 刷新：

```python
    def execute(self) -> None:
        """执行逆回购策略

        流程：
        1. 刷新_today为当天日期（避免长期运行后跨天）
        2. 判断今天是否为节前交易日，不是则跳过
        3. 计算可投入逆回购的资金
        4. 选择合适的逆回购品种
        5. 获取节假日名称
        6. 构建通知消息并推送
        """
        self._today = date.today()
        if not self.should_trigger():
            logger.info("今日(%s)非节前交易日，跳过逆回购策略", self._today)
            return

        # 计算可投金额
        investable = self.calc_investable_amount(self._amount)

        # 选择品种
        code = self.select_code(investable)
        market_label = "沪市" if code == "204001" else "深市"

        # 获取节假日名称
        upcoming = self._calendar.get_upcoming_pre_holidays(self._today)
        holiday_name = upcoming[0][1] if upcoming else "节假日"

        # 构建通知消息
        message = (
            f"{holiday_name}前最后交易日，建议做逆回购\n"
            f"品种：{market_label} {code}\n"
            f"可投金额：{investable:.0f}元"
        )

        self.notify(
            title="逆回购操作提醒",
            message=message,
            event_type="reverse_repo",
        )
        logger.info("已推送逆回购通知: %s %s，可投金额%.0f元", market_label, code, investable)
```

- [ ] **Step 4: 运行逆回购测试通过**

Run: `python -m pytest tests/test_reverse_repo.py -v`
Expected: 全部PASS

- [ ] **Step 5: 写 api_mute days 参数校验测试**

在 `tests/test_dashboard_api.py` 末尾追加：

```python
def test_api_mute_days_validation(app_client):
    """验证days参数必须在1-365范围内"""
    # days=0
    resp = app_client.post("/api/mute", json={"fund_code": "164906", "days": 0})
    assert resp.status_code == 400
    # days=366
    resp = app_client.post("/api/mute", json={"fund_code": "164906", "days": 366})
    assert resp.status_code == 400
    # days=-1
    resp = app_client.post("/api/mute", json={"fund_code": "164906", "days": -1})
    assert resp.status_code == 400
    # days=7 合法
    resp = app_client.post("/api/mute", json={"fund_code": "164906", "days": 7})
    assert resp.status_code == 200
```

- [ ] **Step 6: 运行测试确认失败**

Run: `python -m pytest tests/test_dashboard_api.py::test_api_mute_days_validation -v`
Expected: FAIL — days=0和days=366未返回400

- [ ] **Step 7: 修改 app.py 的 api_mute 增加 days 校验**

在 `dashboard/app.py` 的 `api_mute` 函数中，`fund_code` 校验后增加：

```python
        days = data.get("days", 7)

        if not fund_code:
            return jsonify({"ok": False, "error": "fund_code必填"}), 400

        # days参数校验
        try:
            days = int(days)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "days必须为整数"}), 400
        if days < 1 or days > 365:
            return jsonify({"ok": False, "error": "days必须在1-365范围内"}), 400
```

- [ ] **Step 8: 运行测试确认通过**

Run: `python -m pytest tests/test_dashboard_api.py -v`
Expected: 全部PASS

- [ ] **Step 9: SQLite WAL模式 — 修改 main.py**

在 `main.py` 的 `setup_database` 函数中增加 WAL 模式：

```python
def setup_database(db_path: str) -> sqlite3.Connection:
    """初始化数据库连接并建表

    Args:
        db_path: 数据库文件路径

    Returns:
        已初始化的数据库连接
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)
    return conn
```

同样修改 `dashboard/app.py` 中独立运行时的连接（`__main__` 块）：

在 `conn = sqlite3.connect(DB_PATH, check_same_thread=False)` 后增加：
```python
    conn.execute("PRAGMA journal_mode=WAL")
```

以及 `_get_storage` 中 per-request 连接：
```python
            conn = sqlite3.connect(DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
```

- [ ] **Step 10: 静默过期清理 — 在 app.py 增加 API**

在 `dashboard/app.py` 的 `api_muted_funds` 路由之前增加：

```python
    @app.route("/api/cleanup_expired_mutes", methods=["POST"])
    def api_cleanup_expired_mutes():
        """清理已过期的静默基金，恢复为normal状态"""
        storage = _get_storage()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = storage._conn.execute(
            "SELECT code FROM lof_fund WHERE status='muted' AND muted_until < ? AND muted_until != ''",
            (now_str,),
        )
        expired_codes = [row["code"] for row in cursor.fetchall()]
        for code in expired_codes:
            storage.unmute_fund(code)
        return jsonify({"ok": True, "restored": len(expired_codes)})
```

同时在 `api_muted_funds` 查询之前自动清理过期记录：

```python
    @app.route("/api/muted_funds")
    def api_muted_funds():
        """获取静默基金列表 - 分页查询（自动清理过期静默）"""
        storage = _get_storage()
        # 自动清理已过期的静默基金
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        expired = storage._conn.execute(
            "SELECT code FROM lof_fund WHERE status='muted' AND muted_until < ? AND muted_until != ''",
            (now_str,),
        ).fetchall()
        for row in expired:
            storage.unmute_fund(row["code"])
        # ... 以下原有逻辑不变
```

- [ ] **Step 11: 在 main.py 添加静默过期清理定时任务**

在 `main.py` 的调度器启动前（`scheduler.start()` 之前）增加定时清理任务：

```python
    # 静默过期基金自动清理（每小时检查一次）
    def cleanup_expired_mutes():
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        expired = conn.execute(
            "SELECT code FROM lof_fund WHERE status='muted' AND muted_until < ? AND muted_until != ''",
            (now_str,),
        ).fetchall()
        for row in expired:
            storage.unmute_fund(row["code"])
        if expired:
            logger.info("自动清理%d只过期静默基金", len(expired))

    scheduler._scheduler.add_job(cleanup_expired_mutes, 'interval', hours=1, id='cleanup_expired_mutes')
```

- [ ] **Step 12: 提交**

```bash
git add main.py strategies/reverse_repo.py dashboard/app.py tests/test_reverse_repo.py tests/test_dashboard_api.py
git commit -m "fix: SQLite WAL模式+静默过期自动清理+逆回购_today跨天+days参数校验"
```

---

### Task 5: 前端Bug修复 + 搜索增强 + 安全脱敏 + UI功能

**Files:**
- Modify: `dashboard/templates/index.html`
- Modify: `dashboard/app.py`

- [ ] **Step 1: 修复 statusClass — 增加 running 映射**

在 `index.html` 的 `statusClass` 函数中增加 `running`：

```javascript
    function statusClass(status) {
        if (status === 'ok' || status === 'success' || status === 'running') return 'status-ok';
        if (status === 'failure' || status === 'fail') return 'status-error';
        if (status === 'skip') return 'status-warn';
        return '';
    }
```

- [ ] **Step 2: 修复分页空数据仍显示 — totalPages 条件改为 total > 0**

将 DataTable 模板中的分页条件：

```html
            <div class="dt-pagination" v-if="totalPages > 0">
```

改为：

```html
            <div class="dt-pagination" v-if="total > 0">
```

同样修复静默基金的分页（已正确使用 `mutedTotalPages > 0`，但为一致也改）：

```html
                <div class="dt-pagination" v-if="mutedTotal > 0">
```

- [ ] **Step 3: 配置保存提示3秒后自动消失**

在 `ConfigTab` 的 `saveCategory` 方法中，成功保存后增加 setTimeout 清除提示：

将成功分支的：
```javascript
                        self.saveMsg[cat] = { text: '保存成功(' + data.updated + '项)', cls: 'ok' };
```

改为：
```javascript
                        self.saveMsg[cat] = { text: '保存成功(' + data.updated + '项)', cls: 'ok' };
                        setTimeout(function() { self.saveMsg[cat] = null; }, 3000);
```

失败分支也类似处理：
```javascript
                        self.saveMsg[cat] = { text: '保存失败: ' + (data.error || ''), cls: 'err' };
                        setTimeout(function() { self.saveMsg[cat] = null; }, 3000);
```

无变更提示也处理：
```javascript
                    self.saveMsg[cat] = { text: '无变更', cls: 'err' };
                    setTimeout(function() { self.saveMsg[cat] = null; }, 3000);
```

请求失败也处理：
```javascript
                    self.saveMsg[cat] = { text: '请求失败', cls: 'err' };
                    setTimeout(function() { self.saveMsg[cat] = null; }, 3000);
```

- [ ] **Step 4: 搜索框清空时自动触发 doSearch 恢复完整列表**

在 DataTable 的 `dtInit` 方法中增加 `search` 的 watch 逻辑。由于 Petite-Vue 不支持 watch，改为在 `fetchData` 中处理：在 `fetchData` 的参数构建之前，如果 search 为空字符串则不传 search 参数。

但更直接的方案：在搜索框增加 `@input` 事件，当值为空时自动搜索：

将 DataTable 模板中的搜索框：
```html
                        <input type="text" v-model="search" :placeholder="searchPlaceholder" @keydown.enter="doSearch">
```

改为：
```html
                        <input type="text" v-model="search" :placeholder="searchPlaceholder" @keydown.enter="doSearch" @input="onSearchInput">
```

在 DataTable 组件中增加 `onSearchInput` 方法：
```javascript
            onSearchInput() {
                if (!this.search) {
                    this.doSearch();
                }
            },
```

- [ ] **Step 5: 搜索增强 — 后端增加搜索字段**

修改 `dashboard/app.py` 中的API路由：

**逆回购增加 code 搜索：**
```python
    @app.route("/api/data/reverse_repo")
    def api_data_reverse_repo():
        """逆回购记录 - 分页查询"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "date")
        sort_order = request.args.get("sort_order", "DESC")
        return jsonify(storage.query_paginated(
            "reverse_repo",
            page=page, page_size=page_size,
            search=search, search_columns=["date", "code"],
            order_by=sort_by, order_dir=sort_order,
        ))
```

**告警事件增加搜索（api_status路由）：**

在 `api_status` 中增加搜索参数并传递给 `query_paginated`：
```python
        alert_search = request.args.get("alert_search")
        alert_events = storage.query_paginated(
            "alert_event", page=alert_page, page_size=alert_page_size,
            order_by="timestamp", order_dir="DESC",
            search=alert_search, search_columns=["level", "source", "message"] if alert_search else None,
        )

        notif_search = request.args.get("notif_search")
        notification_logs = storage.query_paginated(
            "notification_log", page=notif_page, page_size=notif_page_size,
            order_by="timestamp", order_dir="DESC",
            search=notif_search, search_columns=["channel", "status", "event_type"] if notif_search else None,
        )
```

**交易信号增加 status 搜索：**
```python
        return jsonify(storage.query_paginated(
            "trade_signal",
            page=page, page_size=page_size,
            search=search, search_columns=["fund_code", "action", "status"],
            order_by=sort_by, order_dir=sort_order,
        ))
```

**LOF溢价历史增加 iopv_source 搜索：**
```python
        return jsonify(storage.query_paginated(
            "premium_history",
            page=page, page_size=page_size,
            search=search, search_columns=["fund_code", "iopv_source"],
            order_by=sort_by, order_dir=sort_order,
        ))
```

- [ ] **Step 6: 前端搜索框更新**

**逆回购搜索框 placeholder 更新：**

```html
                    searchPlaceholder: '搜索日期/代码...',
```

**LOF溢价搜索 placeholder 更新：**
```html
                    searchPlaceholder: '搜索基金代码/IOPV来源...',
```

**交易信号搜索 placeholder 更新：**
```html
                    searchPlaceholder: '搜索基金代码/动作/状态...',
```

**状态总览告警区域增加搜索框：**

在告警事件流 section 的 `<h2>` 后增加搜索框：
```html
                    <div class="dt-search" style="margin-bottom:8px">
                        <input type="text" v-model="alertSearch" placeholder="搜索级别/来源/消息..." @keydown.enter="refreshStatus" @input="if(!alertSearch)refreshStatus()">
                        <button @click="refreshStatus">搜索</button>
                    </div>
```

在 StatusTab 中增加 `alertSearch: ''` 状态字段，并在 `refreshStatus` 的 params 中增加：
```javascript
                if (self.alertSearch) params.set('alert_search', self.alertSearch);
```

**状态总览通知记录增加搜索框：**

在通知记录 section 的 `<h2>` 后增加搜索框：
```html
                    <div class="dt-search" style="margin-bottom:8px">
                        <input type="text" v-model="notifSearch" placeholder="搜索渠道/状态/事件..." @keydown.enter="refreshStatus" @input="if(!notifSearch)refreshStatus()">
                        <button @click="refreshStatus">搜索</button>
                    </div>
```

在 StatusTab 中增加 `notifSearch: ''` 状态字段，并在 `refreshStatus` 的 params 中增加：
```javascript
                if (self.notifSearch) params.set('notif_search', self.notifSearch);
```

- [ ] **Step 7: 敏感配置脱敏 — 后端**

在 `dashboard/app.py` 的 `api_config_get` 中增加脱敏逻辑：

```python
    # 敏感配置键列表
    SENSITIVE_KEYS = {"serverchan_key", "webhook"}

    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        """查询配置项

        Query参数:
            category: 可选，按分类过滤
        """
        cm = _get_config_manager()
        if cm is None:
            return jsonify({"ok": False, "error": "ConfigManager未初始化"}), 503

        category = request.args.get("category")
        items = cm.get_config(category)
        # 敏感字段脱敏：仅显示后4位
        for item in items:
            if item["key"] in SENSITIVE_KEYS and item["value"]:
                val = item["value"]
                if len(val) > 4:
                    item["value"] = "****" + val[-4:]
                else:
                    item["value"] = "****"
        return jsonify({"ok": True, "items": items})
```

修改 `api_config_update`，脱敏格式的值不覆盖原值：

```python
    @app.route("/api/config", methods=["PUT"])
    def api_config_update():
        """批量更新配置

        JSON Body: {"items": [{"category", "section", "key", "value"}]}
        """
        cm = _get_config_manager()
        if cm is None:
            return jsonify({"ok": False, "error": "ConfigManager未初始化"}), 503

        data = request.get_json(force=True)
        items = data.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "items不能为空"}), 400

        # 过滤掉脱敏格式的值（****开头的），不覆盖原值
        real_items = []
        for item in items:
            if item["key"] in SENSITIVE_KEYS and item["value"].startswith("****"):
                continue
            real_items.append(item)

        if real_items:
            cm.update_config(real_items)
        return jsonify({"ok": True, "updated": len(real_items)})
```

- [ ] **Step 8: 敏感配置输入框改为 password 类型**

在 `index.html` 的 ConfigTab 中修改 `getInputType` 方法，增加敏感键判断：

```javascript
            // 敏感配置键
            sensitiveKeys: {'serverchan_key': true, 'webhook': true},

            // 获取控件类型
            getInputType(item) {
                if (this.sensitiveKeys[item.key]) return 'password';
                var vt = (item.value_type || 'string').toLowerCase();
                if (vt === 'bool' || vt === 'boolean') return 'checkbox';
                if (vt === 'int' || vt === 'integer') return 'number';
                if (vt === 'float') return 'number';
                return 'text';
            },
```

同时在配置输入框模板中增加 password 类型的 input：

在 `<!-- 文本类型 -->` 之前增加：
```html
                                <!-- 敏感文本类型（password） -->
                                <input v-if="getInputType(item) === 'password'"
                                       type="password"
                                       :value="item.value"
                                       :placeholder="item.key"
                                       @change="onValueChange(item, $event)">
```

- [ ] **Step 9: api_status 日期查询改为范围查询**

将 `dashboard/app.py` 的 `api_status` 中通知统计的 LIKE 查询改为范围查询：

```python
        # 通知渠道今日统计（使用范围查询替代LIKE）
        today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
        tomorrow_start = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        stats_row = storage._conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success_cnt, "
            "SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) as fail_cnt "
            "FROM notification_log WHERE timestamp >= ? AND timestamp < ?",
            (today_start, tomorrow_start),
        ).fetchone()
```

同样修复策略执行日志的今日次数查询（2处 `LIKE`）：

```python
                cnt_row = storage._conn.execute(
                    "SELECT COUNT(*) as cnt FROM strategy_execution_log "
                    "WHERE strategy_name=? AND trigger_time >= ? AND trigger_time < ?",
                    (se["strategy_name"], today_start, tomorrow_start),
                ).fetchone()
```

- [ ] **Step 10: DataTable 表头点击排序**

在 DataTable 模板中将表头改为可点击排序：

```html
                <thead>
                    <tr>
                        <th v-for="col in columns" @click="toggleSort(col.key)" style="cursor:pointer" :title="'点击排序'">
                            {{ col.label }}
                            <span v-if="sortBy === col.key">{{ sortDir === 'ASC' ? '↑' : '↓' }}</span>
                        </th>
                    </tr>
                </thead>
```

在 DataTable 组件中增加排序状态和方法：

在状态字段中增加：
```javascript
            sortBy: props.defaultSortBy || '',
            sortDir: 'DESC',
```

增加 `toggleSort` 方法：
```javascript
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
```

修改 `fetchData` 中的排序参数：
```javascript
                if (this.sortBy) {
                    params.set('sort_by', this.sortBy);
                    params.set('sort_order', this.sortDir);
                }
```

移除 `defaultSortBy` 在 params 中的使用（已有 `sortBy` 初始化）。

- [ ] **Step 11: 状态总览页增加"立即刷新"按钮**

在状态总览的 `refresh-info` 行后增加刷新按钮：

```html
            <div class="refresh-info">
                上次刷新: {{ refreshTime }}
                <button @click="refreshStatus(); fetchMutedFunds()" style="margin-left:8px;padding:2px 10px;border:1px solid #1890ff;background:#fff;color:#1890ff;border-radius:4px;cursor:pointer;font-size:12px">立即刷新</button>
            </div>
```

- [ ] **Step 12: 运行全部测试确认无回归**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 13: 提交**

```bash
git add dashboard/templates/index.html dashboard/app.py
git commit -m "fix: 前端Bug修复+搜索增强+敏感配置脱敏+表头排序+立即刷新"
```

---

### Task 6: 整体验证

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部PASS

- [ ] **Step 2: 检查测试覆盖率**

Run: `python -m pytest tests/ --cov=. --cov-report=term-missing 2>/dev/null || python -m pytest tests/ -v`
Expected: 无明显覆盖率下降

- [ ] **Step 3: 提交最终状态（如有遗漏修复）**

```bash
git add -A
git commit -m "chore: Bug修复与功能增强完成"
```

---

## Spec Coverage Check

| Spec 需求 | 对应 Task |
|-----------|----------|
| P0: query_paginated 白名单校验 | Task 1 |
| P0: init_from_yaml 逐分类检查 | Task 2 |
| P0: LofFilter _min_volume 属性名 | Task 3 |
| P1: SQLite WAL模式 | Task 4 (Step 9) |
| P1: 静默过期自动恢复 | Task 4 (Step 10-11) |
| P1: 逆回购 _today 跨天 | Task 4 (Step 1-4) |
| P1: api_mute days 校验 | Task 4 (Step 5-8) |
| P1: 风控日计数重置 | **跳过** — RiskChecker未接入main.py |
| 前端: statusClass running | Task 5 (Step 1) |
| 前端: 分页空数据 | Task 5 (Step 2) |
| 前端: 配置保存提示消失 | Task 5 (Step 3) |
| 前端: 搜索框清空刷新 | Task 5 (Step 4) |
| 搜索: 逆回购+code | Task 5 (Step 5) |
| 搜索: 告警事件搜索 | Task 5 (Step 5-6) |
| 搜索: 通知记录搜索 | Task 5 (Step 5-6) |
| 搜索: 交易信号+status | Task 5 (Step 5) |
| 搜索: LOF+iopv_source | Task 5 (Step 5) |
| 安全: 敏感配置脱敏 | Task 5 (Step 7) |
| 安全: 脱敏值不覆盖 | Task 5 (Step 7) |
| 安全: password输入框 | Task 5 (Step 8) |
| 安全: API鉴权 | **跳过** — 本地单机系统过度设计 |
| 功能: 表头排序 | Task 5 (Step 10) |
| 功能: 立即刷新 | Task 5 (Step 11) |
| 功能: 日期范围查询 | Task 5 (Step 9) |
