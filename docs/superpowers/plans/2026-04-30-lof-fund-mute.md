# LOF基金静默功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现LOF基金自动+手动静默功能，暂停申购和无套利空间的基金自动静默，用户可手动静默/解除，静默期间跳过信号但照常记录溢价历史。

**Architecture:** 扩展lof_fund表增加muted_until/mute_reason字段，Storage层新增3个静默方法，DataCollector新增fetch_lof_purchase_status()获取申购数据，Strategy层新增套利利润计算和静默检查，main.py启动时执行自动静默，看板新增3个API端点和静默UI。

**Tech Stack:** Python 3.10+, SQLite, akshare (fund_purchase_em), Flask, Jinja2

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `data/models.py` | Modify | lof_fund表新增muted_until/mute_reason字段DDL + ALTER TABLE迁移 |
| `data/storage.py` | Modify | 新增mute_fund/unmute_fund/list_muted_funds方法 |
| `data/collector.py` | Modify | 新增fetch_lof_purchase_status()方法 |
| `strategies/lof_premium/strategy.py` | Modify | 新增calculate_arbitrage_profit()静态方法 + execute()中增加静默检查 |
| `main.py` | Modify | 启动时执行自动静默逻辑 |
| `config.yaml` | Modify | lof_premium段新增5个配置项 |
| `dashboard/app.py` | Modify | 新增3个API端点 |
| `dashboard/templates/index.html` | Modify | 看板静默UI |
| `tests/test_storage.py` | Modify | 静默方法测试 |
| `tests/test_lof_premium_strategy.py` | Modify | 利润计算+静默检查测试 |
| `tests/test_collector.py` | Modify | fetch_lof_purchase_status测试 |

---

### Task 1: 数据层 — lof_fund表扩展 + Storage静默方法

**Files:**
- Modify: `data/models.py:10-18`
- Modify: `data/storage.py:19-47`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests for mute/unmute/list_muted_funds**

在 `tests/test_storage.py` 末尾追加：

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_storage.py::test_mute_fund tests/test_storage.py::test_unmute_fund tests/test_storage.py::test_list_muted_funds -v`
Expected: FAIL — `AttributeError: 'Storage' object has no attribute 'mute_fund'`

- [ ] **Step 3: Update lof_fund table DDL in models.py**

在 `data/models.py` 中，修改 `lof_fund` 的DDL，在 `daily_volume` 后、`updated_at` 前新增两个字段：

```python
    """CREATE TABLE IF NOT EXISTS lof_fund (
        code TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'normal',
        is_suspended INTEGER NOT NULL DEFAULT 0,
        daily_volume REAL NOT NULL DEFAULT 0.0,
        muted_until TEXT NOT NULL DEFAULT '',
        mute_reason TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (code)
    )""",
```

同时在 `init_db` 函数的 ALTER TABLE 兼容迁移列表中追加：

```python
    # 兼容已有数据库：尝试添加新字段
    for stmt in [
        "ALTER TABLE data_source_status ADD COLUMN last_failure_time TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE data_source_status ADD COLUMN failure_reason TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE lof_fund ADD COLUMN muted_until TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE lof_fund ADD COLUMN mute_reason TEXT NOT NULL DEFAULT ''",
    ]:
```

- [ ] **Step 4: Add mute_fund/unmute_fund/list_muted_funds to Storage**

在 `data/storage.py` 的 `get_lof_fund` 方法后追加三个新方法：

```python
    def mute_fund(self, code: str, muted_until: str, reason: str = "") -> None:
        """设置基金静默状态

        Args:
            code: 基金代码
            muted_until: 静默到期时间，格式 YYYY-MM-DD HH:MM:SS
            reason: 静默原因
        """
        self._conn.execute(
            """UPDATE lof_fund SET status='muted', muted_until=?, mute_reason=?
               WHERE code=?""",
            (muted_until, reason, code),
        )
        self._conn.commit()

    def unmute_fund(self, code: str) -> None:
        """解除基金静默状态，恢复正常

        Args:
            code: 基金代码
        """
        self._conn.execute(
            """UPDATE lof_fund SET status='normal', muted_until='', mute_reason=''
               WHERE code=?""",
            (code,),
        )
        self._conn.commit()

    def list_muted_funds(self) -> List[Dict]:
        """查询所有静默中的基金"""
        cursor = self._conn.execute(
            "SELECT * FROM lof_fund WHERE status='muted'"
        )
        return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_storage.py::test_mute_fund tests/test_storage.py::test_unmute_fund tests/test_storage.py::test_list_muted_funds -v`
Expected: PASS

- [ ] **Step 6: Run full test suite to ensure no regressions**

Run: `python -m pytest tests/test_storage.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add data/models.py data/storage.py tests/test_storage.py
git commit -m "feat: lof_fund表扩展静默字段 + Storage新增mute/unmute/list_muted_funds方法"
```

---

### Task 2: DataCollector — fetch_lof_purchase_status()

**Files:**
- Modify: `data/collector.py`
- Modify: `tests/test_collector.py`

- [ ] **Step 1: Write the failing test for fetch_lof_purchase_status**

在 `tests/test_collector.py` 末尾追加：

```python
def test_fetch_lof_purchase_status():
    """fetch_lof_purchase_status应返回LOF基金的申购状态、限额和费率"""
    import pandas as pd
    from unittest.mock import patch

    collector = _create_collector()

    # 构造fund_purchase_em()的返回数据
    # 列顺序: 基金代码, 基金简称, 基金类型, ... 申购状态(col6), ... 申购累计限额(col10), 购买费率(col11)
    fake_df = pd.DataFrame({
        "基金代码": ["164906", "501050", "162719", "110001"],
        "基金简称": ["LOF-A", "LOF-B", "LOF-C", "非LOF基金"],
        "基金类型": ["LOF", "LOF", "LOF", "股票型"],
        "申购状态": ["正常申购", "限大额", "暂停申购", "正常申购"],
        "赎回状态": ["正常赎回", "正常赎回", "正常赎回", "正常赎回"],
        "申购累计限额": [0, 20000, 0, 0],
        "购买费率": ["0.15%", "0.12%", "0.15%", "1.50%"],
    })

    with patch("akshare.fund_purchase_em", return_value=fake_df, create=True):
        result = collector.fetch_lof_purchase_status()

    # 只应返回LOF类型基金
    assert "164906" in result
    assert "501050" in result
    assert "162719" in result
    assert "110001" not in result  # 非LOF

    # 验证数据格式
    assert result["164906"]["purchase_status"] == "正常申购"
    assert result["164906"]["purchase_limit"] == 0
    assert result["164906"]["purchase_fee_rate"] == 0.0015

    assert result["501050"]["purchase_status"] == "限大额"
    assert result["501050"]["purchase_limit"] == 20000

    assert result["162719"]["purchase_status"] == "暂停申购"
    assert result["162719"]["purchase_limit"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collector.py::test_fetch_lof_purchase_status -v`
Expected: FAIL — `AttributeError: 'DataCollector' object has no attribute 'fetch_lof_purchase_status'`

- [ ] **Step 3: Implement fetch_lof_purchase_status() in collector.py**

在 `data/collector.py` 的 `fetch_reverse_repo_rate` 方法前，`fetch_lof_iopv` 方法后，新增方法：

```python
    # ==================== LOF申购状态 ====================

    def fetch_lof_purchase_status(self) -> Dict[str, Dict]:
        """获取LOF基金申购状态信息

        调用akshare的fund_purchase_em接口获取全市场基金申购信息，
        筛选LOF基金，返回每只LOF的申购状态、限额和费率。

        Returns:
            字典，key为纯数字基金代码，value为申购信息字典：
            {
                "purchase_status": "正常申购" | "限大额" | "暂停申购",
                "purchase_limit": float,  # 申购累计限额（元），0表示无限制
                "purchase_fee_rate": float,  # 申购费率（小数）
            }
        """
        try:
            import akshare as ak
            df = ak.fund_purchase_em()
            if df is None or df.empty:
                logger.warning("fund_purchase_em返回空数据")
                return {}

            result = {}
            for _, row in df.iterrows():
                # 只筛选LOF基金
                fund_type = str(row.get("基金类型", "")).strip()
                if fund_type != "LOF":
                    continue

                code = str(row.get("基金代码", "")).strip()
                if not code:
                    continue

                purchase_status = str(row.get("申购状态", "")).strip()
                # 申购累计限额
                limit_val = row.get("申购累计限额", 0)
                try:
                    purchase_limit = float(limit_val) if limit_val else 0.0
                except (ValueError, TypeError):
                    purchase_limit = 0.0

                # 购买费率，如"0.15%"转为0.0015
                fee_str = str(row.get("购买费率", "0")).strip().replace("%", "")
                try:
                    purchase_fee_rate = float(fee_str) / 100.0 if fee_str else 0.0
                except (ValueError, TypeError):
                    purchase_fee_rate = 0.0

                result[code] = {
                    "purchase_status": purchase_status,
                    "purchase_limit": purchase_limit,
                    "purchase_fee_rate": purchase_fee_rate,
                }

            logger.info("获取LOF申购状态完成，共%d只LOF基金", len(result))
            self._storage.update_data_source_status("lof_purchase", "ok")
            return result
        except Exception as ex:
            logger.error("获取LOF申购状态失败: %s", ex)
            fail_count = self._storage.record_data_source_failure("lof_purchase", str(ex)[:200])
            self._alert_data_source_failure("lof_purchase", fail_count, str(ex))
            return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collector.py::test_fetch_lof_purchase_status -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/collector.py tests/test_collector.py
git commit -m "feat: DataCollector新增fetch_lof_purchase_status获取LOF申购状态"
```

---

### Task 3: Strategy层 — 套利利润计算 + 静默检查

**Files:**
- Modify: `strategies/lof_premium/strategy.py`
- Modify: `tests/test_lof_premium_strategy.py`

- [ ] **Step 1: Write failing tests for calculate_arbitrage_profit**

在 `tests/test_lof_premium_strategy.py` 末尾追加：

```python
def test_calculate_arbitrage_profit_normal():
    """正常情况下计算套利净利润"""
    # 10万资金，3%溢价率，0.15%申购费，万三卖出佣金
    profit = LofPremiumStrategy.calculate_arbitrage_profit(
        premium_rate=3.0,
        purchase_limit=0,  # 无限额
        available_capital=100000,
        purchase_fee_rate=0.0015,
        sell_commission_rate=0.0003,
    )
    # purchasable_amount = min(0, 100000) → 0时取available_capital = 100000
    # gross_profit = 100000 * 3.0 / 100 = 3000
    # purchase_fee = 100000 * 0.0015 = 150
    # sell_commission = 100000 * 0.0003 = 30
    # stamp_duty = 100000 * 0.0005 = 50
    # fixed_costs = 1
    # net_profit = 3000 - 150 - 30 - 50 - 1 = 2769
    assert profit == 2769.0


def test_calculate_arbitrage_profit_with_limit():
    """有限额时按限额计算"""
    profit = LofPremiumStrategy.calculate_arbitrage_profit(
        premium_rate=5.0,
        purchase_limit=10000,  # 只能申购1万
        available_capital=100000,
        purchase_fee_rate=0.0015,
        sell_commission_rate=0.0003,
    )
    # purchasable_amount = min(10000, 100000) = 10000
    # gross_profit = 10000 * 5.0 / 100 = 500
    # purchase_fee = 10000 * 0.0015 = 15
    # sell_commission = 10000 * 0.0003 = 3
    # stamp_duty = 10000 * 0.0005 = 5
    # fixed_costs = 1
    # net_profit = 500 - 15 - 3 - 5 - 1 = 476
    assert profit == 476.0


def test_calculate_arbitrage_profit_low_premium():
    """低溢价率+小限额导致利润不足"""
    profit = LofPremiumStrategy.calculate_arbitrage_profit(
        premium_rate=2.0,
        purchase_limit=20000,  # 只能申购2万
        available_capital=100000,
        purchase_fee_rate=0.0015,
        sell_commission_rate=0.0003,
    )
    # purchasable_amount = 20000
    # gross_profit = 20000 * 2.0 / 100 = 400
    # purchase_fee = 20000 * 0.0015 = 30
    # sell_commission = 20000 * 0.0003 = 6
    # stamp_duty = 20000 * 0.0005 = 10
    # fixed_costs = 1
    # net_profit = 400 - 30 - 6 - 10 - 1 = 353
    assert profit == 353.0


def test_execute_skips_muted_fund():
    """静默基金应跳过信号生成但仍记录溢价历史"""
    strategy = _create_strategy({
        "premium_threshold": 2.0,
        "confirm_count": 1,
        "cooldown_minutes": 0,
        "min_volume": 500,
    })
    # 先插入基金并设为静默
    strategy._storage.upsert_lof_fund("164906", "测试LOF", status="muted",
                                      is_suspended=False, daily_volume=1000.0)
    strategy._storage.mute_fund("164906", "2099-12-31 23:59:59", "暂停申购")

    collector = MagicMock()
    collector.fetch_lof_fund_list.return_value = [
        {"code": "164906", "name": "测试LOF", "status": "normal", "is_suspended": False, "daily_volume": 1000.0},
    ]
    collector.fetch_lof_iopv.return_value = {
        "164906": {"iopv": 1.00, "iopv_source": "estimated"},
    }
    collector.fetch_lof_realtime.return_value = {
        "164906": {"code": "164906", "price": 1.05, "volume": 1000},
    }
    strategy._collector = collector
    strategy.execute()
    # 不应生成信号和通知
    strategy._notifier.notify.assert_not_called()
    signals = strategy._storage.get_trade_signals()
    assert len(signals) == 0
    # 但溢价历史应照常记录
    history = strategy._storage.get_premium_history("164906")
    assert len(history) >= 1


def test_execute_unmutes_expired_fund():
    """静默已过期的基金应自动恢复并生成信号"""
    strategy = _create_strategy({
        "premium_threshold": 2.0,
        "confirm_count": 1,
        "cooldown_minutes": 0,
        "min_volume": 500,
    })
    # 设置一个已过期的静默
    strategy._storage.upsert_lof_fund("164906", "测试LOF", status="muted",
                                      is_suspended=False, daily_volume=1000.0)
    strategy._storage.mute_fund("164906", "2020-01-01 00:00:00", "暂停申购")

    collector = MagicMock()
    collector.fetch_lof_fund_list.return_value = [
        {"code": "164906", "name": "测试LOF", "status": "normal", "is_suspended": False, "daily_volume": 1000.0},
    ]
    collector.fetch_lof_iopv.return_value = {
        "164906": {"iopv": 1.00, "iopv_source": "estimated"},
    }
    collector.fetch_lof_realtime.return_value = {
        "164906": {"code": "164906", "price": 1.05, "volume": 1000},
    }
    strategy._collector = collector
    strategy.execute()
    # 静默已过期，应恢复并生成信号
    strategy._notifier.notify.assert_called_once()
    # 数据库中基金状态应恢复为normal
    fund = strategy._storage.get_lof_fund("164906")
    assert fund["status"] == "normal"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_lof_premium_strategy.py::test_calculate_arbitrage_profit_normal tests/test_lof_premium_strategy.py::test_execute_skips_muted_fund -v`
Expected: FAIL — `AttributeError: type object 'LofPremiumStrategy' has no attribute 'calculate_arbitrage_profit'`

- [ ] **Step 3: Add calculate_arbitrage_profit() static method to strategy.py**

在 `strategies/lof_premium/strategy.py` 的 `LofPremiumStrategy` 类中，`execute` 方法前新增：

```python
    # 印花税率和固定成本
    _STAMP_DUTY_RATE = 0.0005  # 卖出印花税 0.05%
    _FIXED_COSTS = 1.0  # 过户费等固定成本（元）

    @staticmethod
    def calculate_arbitrage_profit(premium_rate: float, purchase_limit: float,
                                   available_capital: float, purchase_fee_rate: float,
                                   sell_commission_rate: float = 0.0003) -> float:
        """计算LOF套利净利润

        Args:
            premium_rate: 当前溢价率(%)
            purchase_limit: 申购累计限额(元)，0表示无限制
            available_capital: 可用资金(元)
            purchase_fee_rate: 申购费率(小数，如0.0015)
            sell_commission_rate: 卖出佣金率(小数)，默认万三

        Returns:
            净利润(元)
        """
        # purchase_limit为0表示无限制，取available_capital
        if purchase_limit <= 0:
            purchasable_amount = available_capital
        else:
            purchasable_amount = min(purchase_limit, available_capital)

        gross_profit = purchasable_amount * premium_rate / 100.0
        purchase_fee = purchasable_amount * purchase_fee_rate
        sell_commission = purchasable_amount * sell_commission_rate
        stamp_duty = purchasable_amount * LofPremiumStrategy._STAMP_DUTY_RATE
        fixed_costs = LofPremiumStrategy._FIXED_COSTS

        return gross_profit - purchase_fee - sell_commission - stamp_duty - fixed_costs
```

- [ ] **Step 4: Add mute check in execute() method**

修改 `strategies/lof_premium/strategy.py` 的 `execute()` 方法。在 `premium_rate >= threshold` 判断之后、`signal_gen.check()` 之前，插入静默检查逻辑：

将现有的：
```python
            # 溢价率未达阈值，跳过信号判断
            if premium_rate < threshold:
                continue

            # 信号防抖判断
            signal = self._signal_gen.check(code, premium_rate)
```

替换为：
```python
            # 溢价率未达阈值，跳过信号判断
            if premium_rate < threshold:
                continue

            # 静默检查：查询lof_fund表
            fund_info = self._storage.get_lof_fund(code)
            if fund_info and fund_info.get("status") == "muted":
                muted_until = fund_info.get("muted_until", "")
                if muted_until and muted_until > now:
                    logger.info("基金%s处于静默期(原因:%s，到期:%s)，跳过信号",
                                code, fund_info.get("mute_reason", ""), muted_until)
                    continue
                else:
                    # 静默已过期，自动恢复
                    logger.info("基金%s静默已过期，自动恢复", code)
                    self._storage.unmute_fund(code)

            # 信号防抖判断
            signal = self._signal_gen.check(code, premium_rate)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_lof_premium_strategy.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add strategies/lof_premium/strategy.py tests/test_lof_premium_strategy.py
git commit -m "feat: LOF策略新增套利利润计算 + 静默基金检查(跳过信号但保留溢价历史)"
```

---

### Task 4: 配置更新 — config.yaml新增静默配置项

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Add new config keys to lof_premium section**

在 `config.yaml` 的 `lof_premium` 段追加5个配置项：

```yaml
# LOF溢价监控配置
lof_premium:
  poll_interval: 60
  random_delay_max: 3
  premium_threshold: 3.0
  low_precision_threshold: 3.0
  min_volume: 500
  confirm_count: 3
  cooldown_minutes: 5
  auto_trade: false
  auto_mute_enabled: true
  min_profit_yuan: 200
  auto_mute_paused_days: 30
  available_capital: 100000
  sell_commission_rate: 0.0003
```

- [ ] **Step 2: Commit**

```bash
git add config.yaml
git commit -m "feat: config.yaml新增LOF静默相关配置项"
```

---

### Task 5: main.py — 启动时自动静默逻辑

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add auto_mute_funds function and call it in main()**

在 `main.py` 的 `run_selfcheck` 函数之后、`main()` 函数之前，新增：

```python
def auto_mute_funds(config: dict, storage: Storage, collector: DataCollector) -> None:
    """系统启动时自动静默无法申购或无套利空间的LOF基金

    Args:
        config: 完整配置字典
        storage: 数据存储实例
        collector: 数据采集器实例
    """
    lof_config = config.get("lof_premium", {})
    if not lof_config.get("auto_mute_enabled", True):
        logger.info("自动静默功能未启用，跳过")
        return

    # 获取申购状态
    try:
        purchase_status = collector.fetch_lof_purchase_status()
    except Exception as ex:
        logger.error("获取LOF申购状态失败，跳过自动静默: %s", ex)
        return

    if not purchase_status:
        logger.info("无LOF申购状态数据，跳过自动静默")
        return

    auto_mute_paused_days = lof_config.get("auto_mute_paused_days", 30)
    min_profit_yuan = lof_config.get("min_profit_yuan", 200)
    available_capital = lof_config.get("available_capital", 100000)
    sell_commission_rate = lof_config.get("sell_commission_rate", 0.0003)

    from datetime import timedelta

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    paused_muted = 0
    profit_muted = 0

    for code, info in purchase_status.items():
        # 检查是否已有手动静默（不覆盖）
        existing = storage.get_lof_fund(code)
        if existing and existing.get("status") == "muted":
            reason = existing.get("mute_reason", "")
            if reason.startswith("手动静默"):
                continue
            # 已静默且未到期，不重复处理
            muted_until = existing.get("muted_until", "")
            if muted_until and muted_until > now_str:
                continue

        # 规则1：暂停申购 → 静默30天
        if info["purchase_status"] == "暂停申购":
            # 先确保基金存在于lof_fund表
            if not existing:
                storage.upsert_lof_fund(code, "", status="normal", is_suspended=False, daily_volume=0.0)
            muted_until = (now + timedelta(days=auto_mute_paused_days)).strftime("%Y-%m-%d %H:%M:%S")
            storage.mute_fund(code, muted_until, "暂停申购")
            paused_muted += 1
            continue

        # 规则2：限大额 → 计算套利利润
        if info["purchase_status"] == "限大额" and info["purchase_limit"] > 0:
            # 获取最近溢价率
            premium_rate = 3.0  # 默认假设值
            if existing:
                history = storage.get_premium_history(code, limit=1)
                if history:
                    premium_rate = abs(history[0].get("premium_rate", 3.0))

            net_profit = LofPremiumStrategy.calculate_arbitrage_profit(
                premium_rate=premium_rate,
                purchase_limit=info["purchase_limit"],
                available_capital=available_capital,
                purchase_fee_rate=info["purchase_fee_rate"],
                sell_commission_rate=sell_commission_rate,
            )

            if net_profit < min_profit_yuan:
                if not existing:
                    storage.upsert_lof_fund(code, "", status="normal", is_suspended=False, daily_volume=0.0)
                # 限大额静默到当天结束
                today_end = now.strftime("%Y-%m-%d") + " 23:59:59"
                storage.mute_fund(code, today_end, "套利利润不足(¥%.0f)" % net_profit)
                profit_muted += 1

    logger.info("自动静默完成: 暂停申购%d只, 利润不足%d只", paused_muted, profit_muted)
```

然后在 `main()` 函数中，在 `run_selfcheck` 调用之前插入自动静默调用：

```python
    # 自动静默无法申购的LOF基金
    auto_mute_funds(config, storage, collector)

    # 启动自检
    if config.get("system", {}).get("startup_selfcheck", True):
        run_selfcheck(config, storage, collector)
```

同时确保 `main.py` 顶部已有 `LofPremiumStrategy` 的导入（当前已有：`from strategies.lof_premium.strategy import LofPremiumStrategy`）。

- [ ] **Step 2: Run full test suite to ensure no regressions**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: 系统启动时自动静默暂停申购和利润不足的LOF基金"
```

---

### Task 6: 看板API — mute/unmute/muted_funds端点

**Files:**
- Modify: `dashboard/app.py`

- [ ] **Step 1: Add three API endpoints to dashboard/app.py**

在 `dashboard/app.py` 中，添加 `json` 和 `request` 导入（`json` 已有），然后追加 `request`：

```python
from flask import Flask, render_template, request, jsonify
```

在 `@app.route("/")` 路由之前，新增三个API端点：

```python
@app.route("/api/mute", methods=["POST"])
def api_mute():
    """手动静默基金"""
    data = request.get_json(force=True)
    fund_code = data.get("fund_code", "")
    days = data.get("days", 7)

    if not fund_code:
        return jsonify({"ok": False, "error": "fund_code必填"}), 400

    conn = get_db()
    storage = Storage(conn)
    # 确保基金存在
    fund = storage.get_lof_fund(fund_code)
    if not fund:
        conn.close()
        return jsonify({"ok": False, "error": "基金不存在"}), 404

    from datetime import timedelta
    muted_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    storage.mute_fund(fund_code, muted_until, "手动静默")
    conn.close()
    return jsonify({"ok": True, "muted_until": muted_until})


@app.route("/api/unmute", methods=["POST"])
def api_unmute():
    """解除基金静默"""
    data = request.get_json(force=True)
    fund_code = data.get("fund_code", "")

    if not fund_code:
        return jsonify({"ok": False, "error": "fund_code必填"}), 400

    conn = get_db()
    storage = Storage(conn)
    storage.unmute_fund(fund_code)
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/muted_funds")
def api_muted_funds():
    """获取所有静默中的基金列表"""
    conn = get_db()
    storage = Storage(conn)
    muted = storage.list_muted_funds()
    conn.close()
    # 只返回关键字段
    result = []
    for f in muted:
        result.append({
            "code": f["code"],
            "name": f["name"],
            "mute_reason": f["mute_reason"],
            "muted_until": f["muted_until"],
        })
    return jsonify(result)
```

同时在 `dashboard/app.py` 顶部添加 Storage 导入：

```python
from data.storage import Storage
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/app.py
git commit -m "feat: 看板新增mute/unmute/muted_funds三个API端点"
```

---

### Task 7: 看板UI — 静默按钮 + 已静默基金区块

**Files:**
- Modify: `dashboard/templates/index.html`

- [ ] **Step 1: Add muted funds section to status overview tab**

在 `index.html` 的状态总览 tab 中，第三行（告警流+通知记录）之后，增加第四行（已静默基金区块）：

在 `</div>` 结束 `id="tab-status"` 之前，即在 `<!-- 业务数据 -->` 之前，追加：

```html
        <!-- 第四行：已静默基金 -->
        <div class="section" id="muted-funds-section">
            <h2>已静默基金</h2>
            <table id="muted-funds-table">
                <thead><tr><th>代码</th><th>名称</th><th>原因</th><th>到期时间</th><th>操作</th></tr></thead>
                <tbody></tbody>
            </table>
            <p class="empty" id="muted-funds-empty" style="display:none">暂无静默基金</p>
        </div>
```

- [ ] **Step 2: Add mute button column to LOF premium table in business data tab**

在业务数据 tab 的 LOF溢价率监控 表格中，增加"操作"列。修改现有的 `premium_history` section：

将 columns 列表从：
```
"columns": ["timestamp", "fund_code", "price", "iopv", "premium_rate", "iopv_source"],
```
改为：
```
"columns": ["timestamp", "fund_code", "price", "iopv", "premium_rate", "iopv_source", "action"],
```

同时在 `dashboard/app.py` 的 index() 路由中，给 `premium_history` 的 rows 添加 action 字段：

在 `dashboard/app.py` 的 index 路由中，修改 premium_history section：

```python
        {
            "title": "LOF溢价率监控",
            "columns": ["timestamp", "fund_code", "price", "iopv", "premium_rate", "iopv_source", "action"],
            "rows": [dict(r, action='<button class="mute-btn" data-code="' + str(r["fund_code"]) + '">静默</button>') for r in conn.execute(
                "SELECT * FROM premium_history ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()],
        },
```

注意：Flask 默认启用 Jinja2 自动转义，需要在模板中用 `|safe` 过滤器显示HTML按钮。修改 index.html 中业务数据表格的 td 输出：

```html
                    {% for row in section.rows %}
                    <tr>
                        {% for col in section.columns %}
                        <td>{{ row[col]|safe }}</td>
                        {% endfor %}
                    </tr>
                    {% endfor %}
```

- [ ] **Step 3: Add JavaScript for mute/unmute interactions + muted funds refresh**

在 `index.html` 的 `<script>` 标签中，在 `refreshStatus` 函数之后追加：

```javascript
function refreshMutedFunds() {
    fetch('/api/muted_funds').then(function(r) { return r.json(); }).then(function(data) {
        var tbody = document.querySelector('#muted-funds-table tbody');
        tbody.innerHTML = '';
        if (data && data.length > 0) {
            data.forEach(function(f) {
                tbody.innerHTML += '<tr><td>' + f.code + '</td><td>' + (f.name || '') +
                    '</td><td>' + f.mute_reason + '</td><td>' + f.muted_until +
                    '</td><td><button class="unmute-btn" data-code="' + f.code + '">解除</button></td></tr>';
            });
            document.getElementById('muted-funds-empty').style.display = 'none';
        } else {
            tbody.innerHTML = '';
            document.getElementById('muted-funds-empty').style.display = 'block';
        }
        // 绑定解除按钮
        document.querySelectorAll('.unmute-btn').forEach(function(btn) {
            btn.onclick = function() { doUnmute(this.getAttribute('data-code')); };
        });
    });
}

function doMute(code) {
    var days = prompt('静默天数:', '7');
    if (days === null) return;
    days = parseInt(days);
    if (isNaN(days) || days <= 0) { alert('请输入有效天数'); return; }
    fetch('/api/mute', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({fund_code: code, days: days})
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.ok) { refreshMutedFunds(); }
        else { alert('静默失败: ' + (data.error || '')); }
    });
}

function doUnmute(code) {
    if (!confirm('确认解除基金 ' + code + ' 的静默？')) return;
    fetch('/api/unmute', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({fund_code: code})
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.ok) { refreshMutedFunds(); }
        else { alert('解除失败: ' + (data.error || '')); }
    });
}

refreshMutedFunds();
setInterval(refreshMutedFunds, 60000);
```

同时在 `refreshStatus()` 函数结尾（`}).catch(...` 之前）追加静默按钮绑定：

```javascript
            // 绑定静默按钮
            document.querySelectorAll('.mute-btn').forEach(function(btn) {
                btn.onclick = function() { doMute(this.getAttribute('data-code')); };
            });
```

注意：由于业务数据 tab 的内容是 Jinja2 服务端渲染的，静默按钮在页面加载时就存在。需要在页面首次加载后也绑定一次，所以在 script 末尾追加：

```javascript
// 初始化绑定业务数据tab中的静默按钮
document.querySelectorAll('.mute-btn').forEach(function(btn) {
    btn.onclick = function() { doMute(this.getAttribute('data-code')); };
});
```

- [ ] **Step 4: Add button style**

在 `<style>` 中追加：

```css
.mute-btn, .unmute-btn { padding: 2px 8px; font-size: 12px; cursor: pointer; border: 1px solid #1890ff; background: #fff; color: #1890ff; border-radius: 3px; }
.mute-btn:hover, .unmute-btn:hover { background: #1890ff; color: #fff; }
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py dashboard/templates/index.html
git commit -m "feat: 看板UI增加静默按钮和已静默基金区块"
```

---

### Task 8: 全量测试 + 端到端验证

**Files:**
- None (验证 only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify dashboard loads correctly**

Run: `python dashboard/app.py` (in background), then fetch `http://localhost:5000/`
Expected: Dashboard renders with new "已静默基金" section and mute buttons

- [ ] **Step 3: Verify API endpoints work**

```bash
curl -X POST http://localhost:5000/api/mute -H "Content-Type: application/json" -d '{"fund_code":"164906","days":7}'
curl http://localhost:5000/api/muted_funds
curl -X POST http://localhost:5000/api/unmute -H "Content-Type: application/json" -d '{"fund_code":"164906"}'
```

Expected: mute returns `{"ok": true}`, muted_funds returns the list, unmute returns `{"ok": true}`

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: 静默功能端到端验证修复"
```
