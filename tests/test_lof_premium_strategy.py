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
