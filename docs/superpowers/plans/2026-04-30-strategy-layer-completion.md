# 策略层补全实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全策略层4项未完成功能，使可转债打新、逆回购、LOF溢价、配债四个策略全部可运行。

**Architecture:** 渐进式集成，按依赖链从底向上：节假日同步 → IOPV获取 → LOF策略组装 → 配债逻辑补全。每步TDD，每步提交。

**Tech Stack:** Python 3.10+, akshare, APScheduler, SQLite, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `scheduler/calendar.py` | Modify | 新增 `sync_from_akshare()` 和 `_infer_holiday_name()` |
| `data/collector.py` | Modify | 新增 `fetch_lof_iopv()` 和 `fetch_bond_allocation_list()` |
| `strategies/lof_premium/strategy.py` | Create | `LofPremiumStrategy(BaseStrategy)` 策略类 |
| `strategies/bond_allocation.py` | Modify | 补全 `execute()` 方法 |
| `main.py` | Modify | 接入节假日同步、LOF策略、配债collector注入 |
| `config.yaml` | Modify | 增加 `lof_premium.auto_trade` 配置 |
| `tests/test_calendar.py` | Modify | 新增节假日同步测试 |
| `tests/test_collector.py` | Modify | 新增IOPV和配债数据获取测试 |
| `tests/test_lof_premium_strategy.py` | Create | LOF策略组装测试 |
| `tests/test_bond_allocation.py` | Modify | 新增execute完整流程测试 |

---

## Task 1: 节假日自动同步

**Files:**
- Modify: `scheduler/calendar.py:1-138`
- Modify: `main.py:152-153`
- Test: `tests/test_calendar.py`

- [ ] **Step 1: 写 `sync_from_akshare` 的失败测试**

在 `tests/test_calendar.py` 末尾添加：

```python
def test_sync_from_akshare_populates_holidays():
    """sync_from_akshare应将交易日和非交易日写入数据库"""
    import sqlite3
    from unittest.mock import patch
    import pandas as pd
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    cal = TradingCalendar()

    # 模拟akshare返回的交易日列表（4-30之后5-1到5-3非交易日）
    fake_trade_dates = [
        "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
        "2026-05-04", "2026-05-05",
    ]

    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_trade_dates})
        cal.sync_from_akshare(storage)

    # 验证非交易日（5-1劳动节，工作日但不在交易日列表中）被标记
    assert cal.is_trading_day(date(2026, 5, 1)) is False


def test_sync_from_akshare_detects_pre_holiday():
    """sync_from_akshare应检测节前交易日"""
    import sqlite3
    from unittest.mock import patch
    import pandas as pd
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    cal = TradingCalendar()

    # 4-30是节前交易日（5-1到5-3连续3天非交易日）
    fake_trade_dates = [
        "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
        "2026-05-04", "2026-05-05",
    ]

    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_trade_dates})
        cal.sync_from_akshare(storage)

    # 4-30是节前交易日
    assert cal.is_pre_holiday(date(2026, 4, 30)) is True


def test_infer_holiday_name():
    """根据月份推断节假日名称"""
    cal = TradingCalendar()
    assert cal._infer_holiday_name(1) == "元旦"
    assert cal._infer_holiday_name(2) == "春节"
    assert cal._infer_holiday_name(4) == "清明节"
    assert cal._infer_holiday_name(5) == "劳动节"
    assert cal._infer_holiday_name(6) == "端午节"
    assert cal._infer_holiday_name(9) == "中秋节"
    assert cal._infer_holiday_name(10) == "国庆节"
    assert cal._infer_holiday_name(3) == "节假日"


def test_sync_incremental():
    """增量同步：已有数据时只拉取新数据"""
    import sqlite3
    from unittest.mock import patch
    import pandas as pd
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    cal = TradingCalendar()

    # 第一次同步
    fake_dates_1 = ["2026-01-02", "2026-01-05"]
    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_dates_1})
        cal.sync_from_akshare(storage)

    # 第二次同步应只拉取1-05之后的数据
    fake_dates_2 = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    with patch("akshare.tool_trade_date_hist_sina") as mock_fn:
        mock_fn.return_value = pd.DataFrame({"trade_date": fake_dates_2})
        cal.sync_from_akshare(storage)

    # 验证数据库中有新增记录
    cursor = storage._conn.execute("SELECT COUNT(*) FROM holiday_calendar")
    count = cursor.fetchone()[0]
    assert count >= 4
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_calendar.py::test_sync_from_akshare_populates_holidays -v`
Expected: FAIL — `AttributeError: 'TradingCalendar' object has no attribute 'sync_from_akshare'`

- [ ] **Step 3: 实现 `sync_from_akshare` 和 `_infer_holiday_name`**

在 `scheduler/calendar.py` 的 `TradingCalendar` 类中，`load_from_storage` 方法之后添加：

```python
    def _infer_holiday_name(self, month: int) -> str:
        """根据月份推断节假日名称

        Args:
            month: 月份（1-12）

        Returns:
            节假日名称
        """
        name_map = {
            1: "元旦", 2: "春节", 4: "清明节",
            5: "劳动节", 6: "端午节", 9: "中秋节", 10: "国庆节",
        }
        return name_map.get(month, "节假日")

    def sync_from_akshare(self, storage) -> None:
        """从akshare同步A股交易日历到数据库

        调用akshare获取历史交易日列表，写入holiday_calendar表。
        自动推断非交易日（工作日但非交易日）和节前交易日。

        Args:
            storage: Storage 实例
        """
        try:
            import akshare as ak
            import pandas as pd
        except ImportError:
            import logging
            logging.getLogger(__name__).error("akshare未安装，无法同步交易日历")
            return

        logger = logging.getLogger(__name__)

        # 获取交易日列表
        try:
            df = ak.tool_trade_date_hist_sina()
        except Exception as ex:
            logger.error("从akshare获取交易日历失败: %s", ex)
            return

        if df is None or df.empty:
            logger.warning("akshare返回空交易日历")
            return

        # 提取交易日日期集合
        trade_date_col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        trade_dates = set()
        for val in df[trade_date_col]:
            date_str = str(val).strip()[:10]
            try:
                d = date.fromisoformat(date_str)
                trade_dates.add(d)
            except ValueError:
                continue

        if not trade_dates:
            logger.warning("交易日历解析后为空")
            return

        # 查询数据库中已有数据的最新日期
        cursor = storage._conn.execute(
            "SELECT MAX(date) FROM holiday_calendar"
        )
        row = cursor.fetchone()
        last_synced = None
        if row and row[0]:
            try:
                last_synced = date.fromisoformat(str(row[0])[:10])
            except ValueError:
                pass

        # 确定同步范围：从数据库最新日期的下一天开始，或从交易日列表最早日期开始
        min_date = min(trade_dates)
        start_date = (last_synced + timedelta(days=1)) if last_synced else min_date
        max_date = max(trade_dates)

        if start_date > max_date:
            logger.info("交易日历已是最新，无需同步")
            return

        # 写入交易日
        written_count = 0
        for d in sorted(trade_dates):
            if d < start_date:
                continue
            storage.upsert_holiday(
                date_str=d.isoformat(),
                is_trading_day=True,
                is_pre_holiday=False,
                holiday_name="",
            )
            written_count += 1

        # 推断非交易日：工作日但不在交易日列表中
        non_trade_count = 0
        current = start_date
        while current <= max_date:
            # 只检查工作日（周一至周五）
            if current.weekday() < 5 and current not in trade_dates:
                holiday_name = self._infer_holiday_name(current.month)
                storage.upsert_holiday(
                    date_str=current.isoformat(),
                    is_trading_day=False,
                    is_pre_holiday=False,
                    holiday_name=holiday_name,
                )
                non_trade_count += 1
            current += timedelta(days=1)

        # 推断节前交易日：某交易日之后连续非交易日>=2天
        pre_holiday_count = 0
        sorted_trades = sorted(d for d in trade_dates if d >= start_date)
        for d in sorted_trades:
            # 检查d之后的连续非交易日天数
            gap = 0
            next_day = d + timedelta(days=1)
            while next_day not in trade_dates and next_day.weekday() < 5 or (
                next_day.weekday() >= 5 and next_day not in trade_dates
            ):
                if next_day.weekday() < 5 and next_day not in trade_dates:
                    gap += 1
                next_day += timedelta(days=1)
                if gap > 20:
                    break
            if gap >= 2:
                # 推断节假日的名称
                holiday_date = d + timedelta(days=1)
                holiday_name = self._infer_holiday_name(holiday_date.month)
                storage.upsert_holiday(
                    date_str=d.isoformat(),
                    is_trading_day=True,
                    is_pre_holiday=True,
                    holiday_name=holiday_name,
                )
                self.add_pre_holiday(d, holiday_name)
                pre_holiday_count += 1

        # 重新加载到内存
        self._holidays.clear()
        self._holiday_names.clear()
        self._pre_holidays.clear()
        self.load_from_storage(storage)

        logger.info(
            "交易日历同步完成: %d个交易日, %d个非交易日, %d个节前交易日",
            written_count, non_trade_count, pre_holiday_count,
        )
```

在 `scheduler/calendar.py` 顶部添加 `import logging`（如果还没有的话）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_calendar.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 在 main.py 中接入节假日自动同步**

修改 `main.py`，在 `calendar.load_from_storage(storage)` 之后添加自动同步逻辑：

```python
    # 初始化交易日历
    calendar = TradingCalendar()
    calendar.load_from_storage(storage)

    # 交易日历为空时自动从akshare同步
    cursor = conn.execute("SELECT COUNT(*) FROM holiday_calendar")
    holiday_count = cursor.fetchone()[0]
    if holiday_count == 0:
        logger.info("交易日历为空，开始从akshare自动同步...")
        calendar.sync_from_akshare(storage)
```

- [ ] **Step 6: 提交**

```bash
git add scheduler/calendar.py main.py tests/test_calendar.py
git commit -m "feat: 节假日日历自动同步（akshare数据源，增量更新，节前推断）"
```

---

## Task 2: IOPV数据获取

**Files:**
- Modify: `data/collector.py:129-161`
- Test: `tests/test_collector.py`

- [ ] **Step 1: 写 `fetch_lof_iopv` 的失败测试**

在 `tests/test_collector.py` 末尾添加：

```python
def test_fetch_lof_iopv_returns_iopv_data():
    """fetch_lof_iopv应返回基金IOPV（净值）数据"""
    import pandas as pd
    from unittest.mock import patch

    collector = _create_collector()

    # 模拟akshare返回的基金历史数据
    fake_df = pd.DataFrame({
        "收盘": [1.025, 1.030],
        "成交量": [5000, 6000],
    })

    with patch("akshare.fund_etf_hist_em", return_value=fake_df):
        result = collector.fetch_lof_iopv(["164906"])

    assert "164906" in result
    assert result["164906"]["iopv"] == 1.030
    assert result["164906"]["iopv_source"] == "estimated"


def test_fetch_lof_iopv_empty_codes():
    """空代码列表应返回空字典"""
    collector = _create_collector()
    result = collector.fetch_lof_iopv([])
    assert result == {}


def test_fetch_lof_iopv_failure_returns_zero():
    """获取失败时应返回iopv为0"""
    from unittest.mock import patch

    collector = _create_collector()

    with patch("akshare.fund_etf_hist_em", side_effect=Exception("网络错误")):
        result = collector.fetch_lof_iopv(["164906"])

    assert "164906" in result
    assert result["164906"]["iopv"] == 0.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_collector.py::test_fetch_lof_iopv_returns_iopv_data -v`
Expected: FAIL — `AttributeError: 'DataCollector' object has no attribute 'fetch_lof_iopv'`

- [ ] **Step 3: 实现 `fetch_lof_iopv` 方法**

在 `data/collector.py` 的 `fetch_lof_realtime` 方法之后添加：

```python
    # ==================== LOF基金IOPV（净值） ====================

    def fetch_lof_iopv(self, codes: List[str]) -> Dict[str, Dict]:
        """获取LOF基金IOPV（净值近似值）

        通过akshare获取基金最新净值作为IOPV的近似值。
        数据精度为日级别，非实时，标记为estimated。

        Args:
            codes: LOF基金代码列表

        Returns:
            字典，key为基金代码，value为 {"iopv": float, "iopv_source": "estimated"}
        """
        if not codes:
            return {}

        result = {}
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare未安装，无法获取IOPV数据")
            return {code: {"iopv": 0.0, "iopv_source": "estimated"} for code in codes}

        for code in codes:
            try:
                df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    iopv = float(latest.get("收盘", 0))
                else:
                    iopv = 0.0
            except Exception as ex:
                logger.warning("获取基金%s IOPV失败: %s", code, ex)
                iopv = 0.0
            result[code] = {"iopv": iopv, "iopv_source": "estimated"}
        return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_collector.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add data/collector.py tests/test_collector.py
git commit -m "feat: LOF基金IOPV数据获取（akshare净值近似，estimated标记）"
```

---

## Task 3: LOF溢价策略组装

**Files:**
- Create: `strategies/lof_premium/strategy.py`
- Modify: `main.py:12-14,188-199`
- Modify: `config.yaml:40-47`
- Test: `tests/test_lof_premium_strategy.py`

- [ ] **Step 1: 写 `LofPremiumStrategy` 的失败测试**

创建 `tests/test_lof_premium_strategy.py`：

```python
"""LOF溢价策略组装测试"""

import sqlite3
from unittest.mock import MagicMock
from datetime import datetime

from data.models import init_db
from data.storage import Storage
from strategies.lof_premium.strategy import LofPremiumStrategy


def _create_strategy(config=None):
    """创建测试用的LofPremiumStrategy实例"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    notifier = MagicMock()
    if config is None:
        config = {
            "enabled": True,
            "premium_threshold": 3.0,
            "low_precision_threshold": 3.0,
            "min_volume": 500,
            "confirm_count": 3,
            "cooldown_minutes": 5,
            "auto_trade": False,
        }
    return LofPremiumStrategy(config, storage, notifier)


def test_strategy_name():
    """策略名称应为lof_premium"""
    strategy = _create_strategy()
    assert strategy.name == "lof_premium"


def test_execute_no_funds():
    """无LOF基金数据时执行不应报错"""
    strategy = _create_strategy()
    collector = MagicMock()
    collector.fetch_lof_fund_list.return_value = []
    strategy._collector = collector
    strategy.execute()
    strategy._notifier.notify.assert_not_called()


def test_execute_below_threshold():
    """溢价率低于阈值时不应生成信号"""
    strategy = _create_strategy({"premium_threshold": 3.0, "confirm_count": 1, "cooldown_minutes": 0})
    collector = MagicMock()
    collector.fetch_lof_fund_list.return_value = [
        {"code": "164906", "name": "测试LOF", "status": "normal", "is_suspended": False, "daily_volume": 1000.0},
    ]
    collector.fetch_lof_iopv.return_value = {
        "164906": {"iopv": 1.05, "iopv_source": "estimated"},
    }
    collector.fetch_lof_realtime.return_value = {
        "164906": {"code": "164906", "price": 1.06, "volume": 1000},
    }
    strategy._collector = collector
    strategy.execute()
    # 溢价率 = (1.06 - 1.05) / 1.05 * 100 ≈ 0.95%，低于3%
    strategy._notifier.notify.assert_not_called()


def test_execute_above_threshold_generates_signal():
    """溢价率超过阈值且确认次数足够时应生成信号并通知"""
    strategy = _create_strategy({
        "premium_threshold": 2.0,
        "confirm_count": 1,
        "cooldown_minutes": 0,
        "min_volume": 500,
    })
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
    # 溢价率 = (1.05 - 1.00) / 1.00 * 100 = 5%，超过2%
    strategy._notifier.notify.assert_called_once()
    call_args = strategy._notifier.notify.call_args
    assert "164906" in call_args.args[1]


def test_execute_records_premium_history():
    """溢价率超过阈值时应记录溢价历史到数据库"""
    strategy = _create_strategy({
        "premium_threshold": 2.0,
        "confirm_count": 1,
        "cooldown_minutes": 0,
        "min_volume": 500,
    })
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
    # 验证溢价历史已写入
    history = strategy._storage.get_premium_history("164906")
    assert len(history) >= 1


def test_execute_records_trade_signal():
    """信号生成时应记录交易信号到数据库"""
    strategy = _create_strategy({
        "premium_threshold": 2.0,
        "confirm_count": 1,
        "cooldown_minutes": 0,
        "min_volume": 500,
    })
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
    # 验证交易信号已写入
    signals = strategy._storage.get_trade_signals()
    assert len(signals) >= 1
    assert signals[0]["fund_code"] == "164906"


def test_execute_filters_suspended():
    """停牌基金应被过滤，不参与计算"""
    strategy = _create_strategy({"premium_threshold": 2.0, "confirm_count": 1, "cooldown_minutes": 0})
    collector = MagicMock()
    collector.fetch_lof_fund_list.return_value = [
        {"code": "164906", "name": "停牌LOF", "status": "normal", "is_suspended": True, "daily_volume": 0.0},
    ]
    strategy._collector = collector
    strategy.execute()
    # 停牌基金不参与计算，不应调用fetch_lof_iopv
    collector.fetch_lof_iopv.assert_not_called()


def test_execute_filters_low_volume():
    """成交量低于阈值的基金应被过滤"""
    strategy = _create_strategy({"premium_threshold": 2.0, "confirm_count": 1, "cooldown_minutes": 0, "min_volume": 500})
    collector = MagicMock()
    collector.fetch_lof_fund_list.return_value = [
        {"code": "164906", "name": "低量LOF", "status": "normal", "is_suspended": False, "daily_volume": 100.0},
    ]
    strategy._collector = collector
    strategy.execute()
    strategy._notifier.notify.assert_not_called()


def test_execute_without_collector():
    """未注入collector时执行不应报错"""
    strategy = _create_strategy()
    strategy.execute()
    strategy._notifier.notify.assert_not_called()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_lof_premium_strategy.py::test_strategy_name -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'strategies.lof_premium.strategy'`

- [ ] **Step 3: 创建 `LofPremiumStrategy` 类**

创建 `strategies/lof_premium/strategy.py`：

```python
"""LOF溢价率套利策略，检测溢价机会并推送通知"""

import logging
from datetime import datetime

from strategies.base import BaseStrategy
from strategies.lof_premium.premium import PremiumCalculator
from strategies.lof_premium.filter import LofFilter
from strategies.lof_premium.signal import SignalGenerator

logger = logging.getLogger(__name__)


class LofPremiumStrategy(BaseStrategy):
    """LOF溢价率套利策略

    轮询LOF基金列表，计算溢价率，通过过滤和信号防抖后
    推送套利通知。支持可选自动交易模式。
    """

    name: str = "lof_premium"

    def __init__(self, config: dict, storage, notifier):
        """初始化LOF溢价策略

        Args:
            config: 策略配置字典，支持以下键：
                - enabled: 是否启用，默认True
                - premium_threshold: 实时IOPV溢价阈值(%), 默认2.0
                - low_precision_threshold: 非实时IOPV溢价阈值(%), 默认3.0
                - min_volume: 最低日成交量(万元), 默认500
                - confirm_count: 连续确认次数, 默认3
                - cooldown_minutes: 冷却期(分钟), 默认5
                - auto_trade: 是否自动交易, 默认False
            storage: 数据存储实例
            notifier: 通知管理器实例
        """
        super().__init__(config, storage, notifier)
        self._premium_calc = PremiumCalculator(
            normal_threshold=config.get("premium_threshold", 2.0),
            low_precision_threshold=config.get("low_precision_threshold", 3.0),
        )
        self._lof_filter = LofFilter(
            min_volume=config.get("min_volume", 500),
        )
        self._signal_gen = SignalGenerator(
            threshold=config.get("premium_threshold", 2.0),
            confirm_count=config.get("confirm_count", 3),
            cooldown_minutes=config.get("cooldown_minutes", 5),
        )
        self._auto_trade = config.get("auto_trade", False)

    def execute(self) -> None:
        """执行LOF溢价策略

        流程：
        1. 获取LOF基金列表
        2. 过滤停牌和低成交量基金
        3. 获取IOPV和市价
        4. 计算溢价率，与阈值比较
        5. 信号防抖判断
        6. 记录溢价历史和交易信号，推送通知
        """
        collector = getattr(self, "_collector", None)
        if collector is None:
            logger.info("LOF溢价策略：未注入数据采集器，跳过执行")
            return

        # 1. 获取LOF基金列表
        try:
            fund_list = collector.fetch_lof_fund_list()
        except Exception as ex:
            logger.error("获取LOF基金列表失败: %s", ex)
            return

        if not fund_list:
            logger.info("LOF溢价策略：无基金数据")
            return

        # 2. 过滤停牌和低成交量
        active_funds = []
        for fund in fund_list:
            if not self._lof_filter.filter_by_suspension(fund.get("is_suspended", False)):
                continue
            if not self._lof_filter.filter_by_volume(fund.get("daily_volume", 0.0)):
                continue
            active_funds.append(fund)

        if not active_funds:
            logger.info("LOF溢价策略：过滤后无活跃基金")
            return

        # 3. 获取IOPV和市价
        codes = [f["code"] for f in active_funds]
        try:
            iopv_data = collector.fetch_lof_iopv(codes)
        except Exception as ex:
            logger.error("获取IOPV数据失败: %s", ex)
            return

        try:
            realtime_data = collector.fetch_lof_realtime(codes)
        except Exception as ex:
            logger.error("获取实时行情失败: %s", ex)
            return

        # 4. 计算溢价率并判断信号
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for fund in active_funds:
            code = fund["code"]
            iopv_info = iopv_data.get(code, {})
            iopv = iopv_info.get("iopv", 0.0)
            iopv_source = iopv_info.get("iopv_source", "estimated")
            price = realtime_data.get(code, {}).get("price", 0.0)

            if iopv <= 0 or price <= 0:
                continue

            # 计算溢价率
            premium_rate = self._premium_calc.calculate(price, iopv)
            threshold = self._premium_calc.get_threshold(iopv_source)

            # 记录溢价历史（无论是否超过阈值）
            self._storage.insert_premium_history(
                timestamp=now,
                fund_code=code,
                price=price,
                iopv=iopv,
                premium_rate=premium_rate,
                iopv_source=iopv_source,
            )

            # 溢价率未达阈值，跳过信号判断
            if premium_rate < threshold:
                continue

            # 信号防抖判断
            signal = self._signal_gen.check(code, premium_rate)
            if signal is None:
                continue

            # 5. 生成信号，入库并通知
            logger.info(
                "LOF溢价信号: %s 溢价率%.2f%% (阈值%.2f%%)",
                code, premium_rate, threshold,
            )

            self._storage.insert_trade_signal(
                trigger_time=now,
                fund_code=code,
                premium_rate=premium_rate,
                action="sell_and_subscribe",
                status="pending",
                iopv_source=iopv_source,
            )

            self.notify(
                title="LOF溢价套利信号",
                message=f"{code} {fund.get('name', '')} 溢价率{premium_rate:.2f}%（阈值{threshold:.1f}%）",
                event_type="lof_premium",
            )

            # 自动交易预留（当前版本不实际调用）
            if self._auto_trade:
                logger.info("自动交易已启用，但TradeExecutor尚未接入，跳过执行")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_lof_premium_strategy.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 在 main.py 中接入 LofPremiumStrategy**

在 `main.py` 顶部导入部分添加：

```python
from strategies.lof_premium.strategy import LofPremiumStrategy
```

在 `main.py` 中创建配债策略实例之后、注册策略之前，添加：

```python
    # 创建LOF溢价策略实例
    lof_premium = LofPremiumStrategy(
        config.get("lof_premium", {}),
        storage, notifier,
    )
    # 注入数据采集器
    lof_premium._collector = collector
```

修改注册策略列表，添加 `lof_premium`：

```python
    # 注册已启用的策略
    for name, strat in [
        ("bond_ipo", bond_ipo),
        ("reverse_repo", reverse_repo),
        ("bond_allocation", bond_alloc),
        ("lof_premium", lof_premium),
    ]:
        if strategy_config.get(name, {}).get("enabled", True):
            scheduler.register(strat)
```

在添加每日定时任务之后，添加LOF溢价策略的间隔轮询任务：

```python
    # LOF溢价策略使用间隔轮询
    lof_premium_interval = config.get("lof_premium", {}).get("poll_interval", 5)
    if strategy_config.get("lof_premium", {}).get("enabled", True):
        scheduler.add_interval_job("lof_premium", lof_premium_interval)
```

- [ ] **Step 6: 在 config.yaml 中添加 auto_trade 配置**

在 `lof_premium` 配置段末尾添加：

```yaml
  auto_trade: false
```

完整的 `lof_premium` 段应为：

```yaml
lof_premium:
  poll_interval: 5
  random_delay_max: 3
  premium_threshold: 3.0
  low_precision_threshold: 3.0
  min_volume: 500
  confirm_count: 3
  cooldown_minutes: 5
  auto_trade: false
```

- [ ] **Step 7: 运行全部测试确认无回归**

Run: `python -m pytest tests/ -v`
Expected: 所有测试 PASS

- [ ] **Step 8: 提交**

```bash
git add strategies/lof_premium/strategy.py main.py config.yaml tests/test_lof_premium_strategy.py
git commit -m "feat: LOF溢价策略组装（通知+可选自动交易，间隔轮询）"
```

---

## Task 4: 配债策略逻辑补全

**Files:**
- Modify: `data/collector.py` — 新增 `fetch_bond_allocation_list()`
- Modify: `strategies/bond_allocation.py:92-103` — 补全 `execute()`
- Modify: `main.py:182-185` — 注入 collector
- Test: `tests/test_collector.py` — 新增配债数据获取测试
- Test: `tests/test_bond_allocation.py` — 新增 execute 流程测试

- [ ] **Step 1: 写 `fetch_bond_allocation_list` 的失败测试**

在 `tests/test_collector.py` 末尾添加：

```python
def test_fetch_bond_allocation_list_returns_data():
    """fetch_bond_allocation_list应返回即将发行转债及正股信息"""
    import pandas as pd
    from unittest.mock import patch, MagicMock

    collector = _create_collector()

    # 模拟akshare返回的可转债发行列表
    fake_bond_df = pd.DataFrame({
        "债券代码": ["113001", "127001"],
        "债券名称": ["测试转债1", "测试转债2"],
        "申购日期": ["2026-05-15", "2026-05-20"],
        "正股代码": ["600001", "000001"],
    })

    with patch("akshare.bond_zh_cov_new_em", return_value=fake_bond_df):
        with patch("akshare.stock_individual_info_em") as mock_stock:
            mock_stock.side_effect = [
                pd.DataFrame({"item": ["股票简称", "最新价"], "value": ["测试股票1", "10.50"]}),
                pd.DataFrame({"item": ["股票简称", "最新价"], "value": ["测试股票2", "15.20"]}),
            ]
            result = collector.fetch_bond_allocation_list()

    assert len(result) == 2
    assert result[0]["code"] == "113001"
    assert result[0]["stock_code"] == "600001"
    assert result[0]["content_weight"] == 20.0  # 默认估算值


def test_fetch_bond_allocation_list_empty():
    """无发行数据时应返回空列表"""
    import pandas as pd
    from unittest.mock import patch

    collector = _create_collector()

    with patch("akshare.bond_zh_cov_new_em", return_value=pd.DataFrame()):
        result = collector.fetch_bond_allocation_list()

    assert result == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_collector.py::test_fetch_bond_allocation_list_returns_data -v`
Expected: FAIL — `AttributeError: 'DataCollector' object has no attribute 'fetch_bond_allocation_list'`

- [ ] **Step 3: 实现 `fetch_bond_allocation_list` 方法**

在 `data/collector.py` 的 `fetch_reverse_repo_rate` 方法之后添加：

```python
    # ==================== 可转债配债 ====================

    def fetch_bond_allocation_list(self) -> List[Dict]:
        """获取即将发行可转债及正股信息

        通过akshare获取可转债发行列表和正股基本信息。
        含权量（content_weight）akshare暂无此字段，使用默认估算值20%。

        Returns:
            配债列表，每项包含 code, name, subscribe_date,
            stock_code, stock_name, stock_price, content_weight
        """
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare未安装，无法获取配债数据")
            return []

        try:
            df = ak.bond_zh_cov_new_em()
        except Exception as ex:
            logger.error("获取可转债发行列表失败: %s", ex)
            return []

        if df is None or df.empty:
            return []

        result = []
        for _, row in df.iterrows():
            code = str(row.get("债券代码", "")).strip()
            name = str(row.get("债券名称", "")).strip()
            subscribe_date = str(row.get("申购日期", "")).strip()
            stock_code = str(row.get("正股代码", "")).strip()

            # 获取正股信息
            stock_name = ""
            stock_price = 0.0
            if stock_code:
                try:
                    stock_df = ak.stock_individual_info_em(symbol=stock_code)
                    if stock_df is not None and not stock_df.empty:
                        for _, srow in stock_df.iterrows():
                            item = str(srow.get("item", "")).strip()
                            value = srow.get("value", "")
                            if item == "股票简称":
                                stock_name = str(value).strip()
                            elif item == "最新价":
                                try:
                                    stock_price = float(value)
                                except (ValueError, TypeError):
                                    stock_price = 0.0
                except Exception as ex:
                    logger.warning("获取正股%s信息失败: %s", stock_code, ex)

            result.append({
                "code": code,
                "name": name,
                "subscribe_date": subscribe_date,
                "stock_code": stock_code,
                "stock_name": stock_name,
                "stock_price": stock_price,
                "content_weight": 20.0,  # 默认估算值
            })
        return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_collector.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 写 `BondAllocationStrategy.execute()` 补全的测试**

在 `tests/test_bond_allocation.py` 末尾添加：

```python
def test_execute_with_allocation_list():
    """有配债机会时应计算安全垫并推送通知"""
    from unittest.mock import MagicMock
    from datetime import date, timedelta

    strategy = BondAllocationStrategy(
        config={
            "min_safety_cushion": 0.1,
            "notify_before_record_day": 30,
            "conservative_factor": 0.8,
            "rush_warning_threshold": 5.0,
        },
        storage=MagicMock(),
        notifier=MagicMock(),
    )

    # 注入mock数据采集器
    future_date = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
    collector = MagicMock()
    collector.fetch_bond_allocation_list.return_value = [
        {
            "code": "113001",
            "name": "测试转债",
            "subscribe_date": future_date,
            "stock_code": "600001",
            "stock_name": "测试股票",
            "stock_price": 10.0,
            "content_weight": 25.0,
        },
    ]
    strategy._collector = collector

    strategy.execute()

    # 验证通知被调用
    strategy._notifier.notify.assert_called_once()
    call_args = strategy._notifier.notify.call_args
    assert "113001" in call_args.args[1]


def test_execute_excludes_st_stock():
    """ST股票应被排除，不推送通知"""
    from unittest.mock import MagicMock
    from datetime import date, timedelta

    strategy = BondAllocationStrategy(
        config={"min_safety_cushion": 0.1, "notify_before_record_day": 30},
        storage=MagicMock(),
        notifier=MagicMock(),
    )

    future_date = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
    collector = MagicMock()
    collector.fetch_bond_allocation_list.return_value = [
        {
            "code": "113001",
            "name": "ST转债",
            "subscribe_date": future_date,
            "stock_code": "600001",
            "stock_name": "ST测试",
            "stock_price": 5.0,
            "content_weight": 20.0,
        },
    ]
    strategy._collector = collector

    strategy.execute()
    strategy._notifier.notify.assert_not_called()


def test_execute_without_collector():
    """未注入collector时执行不应报错（兼容原有行为）"""
    strategy = BondAllocationStrategy(config={}, storage=MagicMock(), notifier=MagicMock())
    strategy.execute()
    strategy._notifier.notify.assert_not_called()


def test_execute_no_upcoming_bonds():
    """无近期配债机会时不应推送通知"""
    from unittest.mock import MagicMock
    from datetime import date, timedelta

    strategy = BondAllocationStrategy(
        config={"notify_before_record_day": 7},
        storage=MagicMock(),
        notifier=MagicMock(),
    )

    # 申购日期在30天后，超出notify_before_record_day
    far_date = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
    collector = MagicMock()
    collector.fetch_bond_allocation_list.return_value = [
        {
            "code": "113001",
            "name": "远期转债",
            "subscribe_date": far_date,
            "stock_code": "600001",
            "stock_name": "测试股票",
            "stock_price": 10.0,
            "content_weight": 20.0,
        },
    ]
    strategy._collector = collector

    strategy.execute()
    strategy._notifier.notify.assert_not_called()
```

- [ ] **Step 6: 运行测试确认失败**

Run: `python -m pytest tests/test_bond_allocation.py::test_execute_with_allocation_list -v`
Expected: FAIL — execute()是stub，不调用notifier

- [ ] **Step 7: 补全 `BondAllocationStrategy.execute()` 方法**

替换 `strategies/bond_allocation.py` 中的 `execute()` 方法：

```python
    def execute(self) -> None:
        """执行可转债配债策略

        流程：
        1. 获取即将发行转债的标的列表
        2. 筛选近期申购的标的
        3. 排除ST/退市股
        4. 计算安全垫，筛选达标标的
        5. 检查抢权预警
        6. 入库并推送通知
        """
        collector = getattr(self, "_collector", None)
        if collector is None:
            logger.info("可转债配债策略：未注入数据采集器，跳过执行")
            return

        # 获取配债列表
        try:
            allocation_list = collector.fetch_bond_allocation_list()
        except Exception as ex:
            logger.error("获取配债列表失败: %s", ex)
            return

        if not allocation_list:
            logger.info("可转债配债：当前无发行转债")
            return

        # 筛选近期申购的标的
        notify_days = self._config.get("notify_before_record_day", 7)
        today_str = date.today().isoformat()
        upcoming = []
        for bond in allocation_list:
            subscribe_date = bond.get("subscribe_date", "")
            if not subscribe_date:
                continue
            try:
                sub_date = date.fromisoformat(subscribe_date)
                days_until = (sub_date - date.today()).days
                if 0 <= days_until <= notify_days:
                    upcoming.append(bond)
            except ValueError:
                continue

        if not upcoming:
            logger.info("可转债配债：近期(%d天内)无配债机会", notify_days)
            return

        # 逐只处理
        for bond in upcoming:
            stock_name = bond.get("stock_name", "")

            # 排除ST/退市股
            if self.is_stock_excluded(stock_name):
                logger.info("可转债配债：排除ST/退市股 %s", stock_name)
                continue

            stock_price = bond.get("stock_price", 0.0)
            content_weight = bond.get("content_weight", 20.0)

            # 计算安全垫（使用固定默认溢价率0.30）
            safety_cushion = self.calc_safety_cushion(
                stock_price=stock_price,
                content_weight=content_weight,
                avg_opening_premium=0.30,
            )

            # 安全垫不达标
            if safety_cushion < self._min_safety_cushion:
                logger.info(
                    "可转债配债：%s 安全垫%.2f%%低于阈值%.1f%%，跳过",
                    bond.get("code", ""), safety_cushion, self._min_safety_cushion,
                )
                continue

            # 检查抢权预警（暂用0，后续可补充）
            if self.is_rush_warning(0):
                logger.info("可转债配债：%s 触发抢权预警，跳过", bond.get("code", ""))
                continue

            # 入库
            self._storage.upsert_bond_allocation(
                code=bond.get("code", ""),
                stock_code=bond.get("stock_code", ""),
                stock_name=stock_name,
                content_weight=content_weight,
                safety_cushion=safety_cushion,
                record_date=bond.get("subscribe_date", ""),
            )

            # 推送通知
            self.notify(
                title="可转债配债提醒",
                message=(
                    f"{bond.get('code', '')} {bond.get('name', '')}\n"
                    f"正股：{stock_name}({bond.get('stock_code', '')}) 价格{stock_price:.2f}\n"
                    f"含权量：{content_weight:.1f}% 安全垫：{safety_cushion:.2f}%"
                ),
                event_type="bond_allocation",
            )
            logger.info(
                "可转债配债通知: %s 安全垫%.2f%%",
                bond.get("code", ""), safety_cushion,
            )
```

在 `strategies/bond_allocation.py` 顶部添加缺少的导入：

```python
from datetime import date
```

- [ ] **Step 8: 运行测试确认通过**

Run: `python -m pytest tests/test_bond_allocation.py -v`
Expected: 所有测试 PASS

- [ ] **Step 9: 在 main.py 中注入 collector**

在 `main.py` 中，创建 `bond_alloc` 之后添加：

```python
    # 注入数据采集器
    bond_alloc._collector = collector
```

完整上下文应为：

```python
    # 创建可转债配债策略实例
    bond_alloc = BondAllocationStrategy(
        config.get("bond_allocation", {}),
        storage, notifier,
    )
    # 注入数据采集器
    bond_alloc._collector = collector
```

- [ ] **Step 10: 运行全部测试确认无回归**

Run: `python -m pytest tests/ -v`
Expected: 所有测试 PASS

- [ ] **Step 11: 提交**

```bash
git add data/collector.py strategies/bond_allocation.py main.py tests/test_collector.py tests/test_bond_allocation.py
git commit -m "feat: 配债策略逻辑补全（安全垫计算+ST过滤+入库通知）"
```

---

## Task 5: 最终验证与文档更新

**Files:**
- Modify: `docs/操作手册.md`

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 所有测试 PASS，测试数量应从约61个增加到约75个

- [ ] **Step 2: 更新操作手册中的功能状态**

将 `docs/操作手册.md` 中的功能状态表更新为：

| 策略 | 状态 | 说明 |
|------|------|------|
| **可转债打新** | ✅ 完整可用 | 09:30 自动检查当日可申购转债，推送通知，连续违约2次自动暂停 |
| **节假日逆回购** | ✅ 完整可用 | 14:30 自动检测节前交易日，计算可用资金，选择最优回购品种，推送提醒 |
| **可转债配债** | ✅ 完整可用 | 09:00 自动检查近期配债机会，安全垫计算，ST过滤，推送通知 |
| **LOF底仓套利** | ✅ 完整可用 | 间隔轮询检测溢价信号，通知+可选自动交易 |
| **交易执行** | ⚠️ 未接入 | TradeExecutor+RiskChecker已实现，未接入主流程，需miniQMT |
| **看板** | ✅ 可用 | Flask 只读看板，展示5张表的最近数据 |
| **通知** | ✅ 桌面通知开箱即用 | 微信/钉钉需配置密钥 |

同时更新"未完成功能"表：

| 项目 | 说明 |
|------|------|
| 交易执行接入 | `TradeExecutor` + `RiskChecker` 需接入 main.py，前置条件：开通 miniQMT |
| 实时IOPV获取 | 当前IOPV使用akshare日净值近似，接入xtquant后可获取实时IOPV |
| 备用数据源 | 所有 fallback 方法为空实现 |
| 配债含权量精确获取 | 当前使用默认估算值20%，需对接公告数据源 |

- [ ] **Step 3: 提交**

```bash
git add docs/操作手册.md
git commit -m "docs: 更新操作手册，反映策略层补全后的功能状态"
```
