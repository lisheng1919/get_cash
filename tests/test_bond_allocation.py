"""可转债配债策略单元测试"""

from strategies.bond_allocation import BondAllocationStrategy


def test_safety_cushion_calculation():
    """安全垫计算：保守系数0.8，正股10元，含权25%，溢价30%"""
    strategy = BondAllocationStrategy(
        config={"min_content_weight": 20, "min_safety_cushion": 5.0, "conservative_factor": 0.8},
        storage=None, notifier=None,
    )
    cushion = strategy.calc_safety_cushion(
        stock_price=10.0,
        content_weight=25.0,
        avg_opening_premium=0.30,
    )
    assert cushion > 0
    # 保守估值: 100 * (1 + 0.30 * 0.8) = 124
    # 每百元正股配债收益: (124 - 100) * 25 / 100 = 6
    # 安全垫: 6 / (10 * 100) * 100 = 0.6%
    assert abs(cushion - 0.6) < 0.01


def test_safety_cushion_zero_stock_price():
    """正股价格为0时安全垫应返回0"""
    strategy = BondAllocationStrategy(
        config={"conservative_factor": 0.8},
        storage=None, notifier=None,
    )
    assert strategy.calc_safety_cushion(0, 25, 0.3) == 0.0


def test_rush_warning():
    """抢权预警：涨幅达到或超过阈值时触发"""
    strategy = BondAllocationStrategy(
        config={"rush_warning_threshold": 5.0},
        storage=None, notifier=None,
    )
    assert strategy.is_rush_warning(6.0) is True
    assert strategy.is_rush_warning(3.0) is False
    assert strategy.is_rush_warning(5.0) is True


def test_stock_filter_st():
    """股票排除：ST、*ST、退市前缀的股票应被排除"""
    strategy = BondAllocationStrategy(config={}, storage=None, notifier=None)
    assert strategy.is_stock_excluded("*ST华仪") is True
    assert strategy.is_stock_excluded("ST明科") is True
    assert strategy.is_stock_excluded("退市海润") is True
    assert strategy.is_stock_excluded("双乐股份") is False


def test_conservative_factor():
    """保守系数影响：0.6保守系数下安全垫应更低"""
    strategy = BondAllocationStrategy(
        config={"conservative_factor": 0.6},
        storage=None, notifier=None,
    )
    # 保守系数0.6: 100 * (1 + 0.30 * 0.6) = 118
    # 收益: (118-100)*25/100 = 4.5, 安全垫: 4.5/1000*100 = 0.45%
    cushion = strategy.calc_safety_cushion(10.0, 25.0, 0.30)
    assert abs(cushion - 0.45) < 0.01


def test_execute_logs_message():
    """execute()执行时应输出日志"""
    from unittest.mock import MagicMock
    strategy = BondAllocationStrategy(config={}, storage=MagicMock(), notifier=MagicMock())
    strategy.execute()  # 不应抛出异常


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
    """未注入collector时执行不应报错"""
    from unittest.mock import MagicMock
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
