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


def test_calculate_arbitrage_profit_normal():
    """正常情况下计算套利净利润"""
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
