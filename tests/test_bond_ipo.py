"""可转债打新策略单元测试"""

import sqlite3
from unittest.mock import MagicMock

from data.models import init_db
from data.storage import Storage
from strategies.bond_ipo import BondIpoStrategy


def _create_strategy(config=None):
    """创建测试用的BondIpoStrategy实例"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    notifier = MagicMock()
    if config is None:
        config = {"enabled": True, "auto_subscribe": True, "max_consecutive_miss": 2}
    return BondIpoStrategy(config, storage, notifier)


def test_bond_ipo_auto_suspend_on_miss():
    """连续未中签达到阈值时应暂停"""
    strategy = _create_strategy()
    strategy._consecutive_miss = 2
    assert strategy.should_suspend() is True


def test_bond_ipo_not_suspend_below_threshold():
    """连续未中签未达阈值时不应暂停"""
    strategy = _create_strategy()
    strategy._consecutive_miss = 1
    assert strategy.should_suspend() is False


def test_bond_ipo_market_code():
    """根据债券代码判断市场：11开头为沪市，其他为深市"""
    strategy = _create_strategy()
    assert strategy.get_market("113xxx") == "sh"
    assert strategy.get_market("127xxx") == "sz"


def test_bond_ipo_execute_with_suspend():
    """暂停状态下执行策略不应发送通知"""
    strategy = _create_strategy()
    strategy._consecutive_miss = 2
    strategy.execute()
    strategy._notifier.notify.assert_not_called()


def test_bond_ipo_execute_without_collector():
    """未注入数据采集器时执行策略不应报错"""
    strategy = _create_strategy()
    strategy.execute()
    strategy._notifier.notify.assert_not_called()


def test_bond_ipo_execute_with_today_bonds():
    """有今日新债时应入库并推送通知"""
    strategy = _create_strategy()

    # 注入mock数据采集器
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    collector = MagicMock()
    collector.fetch_bond_ipo_list.return_value = [
        {"code": "113001", "name": "测试转债1", "subscribe_date": today},
        {"code": "127001", "name": "测试转债2", "subscribe_date": today},
    ]
    strategy._collector = collector

    strategy.execute()

    # 验证通知被调用2次
    assert strategy._notifier.notify.call_count == 2
    # 验证通知内容（notify通过位置参数调用：title, message, event_type）
    calls = strategy._notifier.notify.call_args_list
    assert "113001" in calls[0].args[1]
    assert "127001" in calls[1].args[1]
    # 验证入库
    bond = strategy._storage.get_pending_bond_ipo()
    assert len(bond) == 2


def test_bond_ipo_execute_no_bonds_today():
    """今日无新债时不应推送通知"""
    strategy = _create_strategy()

    collector = MagicMock()
    # 返回昨日的新债
    collector.fetch_bond_ipo_list.return_value = [
        {"code": "113001", "name": "旧转债", "subscribe_date": "2025-01-01"},
    ]
    strategy._collector = collector

    strategy.execute()
    strategy._notifier.notify.assert_not_called()
