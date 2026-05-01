"""节假日逆回购策略单元测试"""

import sqlite3
from datetime import date
from unittest.mock import MagicMock

from data.models import init_db
from data.storage import Storage
from scheduler.calendar import TradingCalendar
from strategies.reverse_repo import ReverseRepoStrategy


def _create_strategy(config=None, calendar=None):
    """创建测试用的ReverseRepoStrategy实例"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    notifier = MagicMock()
    if calendar is None:
        calendar = TradingCalendar()
    if config is None:
        config = {
            "enabled": True,
            "min_rate": 3.0,
            "reserve_ratio": 0.2,
            "amount": 100000,
            "prefer_sh": True,
        }
    return ReverseRepoStrategy(config, storage, notifier, calendar)


def test_reverse_repo_not_triggered_on_normal_day():
    """普通交易日不应触发逆回购策略"""
    strategy = _create_strategy()
    strategy._today = date(2026, 4, 29)  # 普通日
    assert strategy.should_trigger() is False


def test_reverse_repo_triggered_on_pre_holiday():
    """节前交易日应触发逆回购策略"""
    calendar = TradingCalendar()
    calendar.add_pre_holiday(date(2026, 9, 30), "国庆节前")
    strategy = _create_strategy(calendar=calendar)
    strategy._today = date(2026, 9, 30)
    assert strategy.should_trigger() is True


def test_reverse_repo_reserve_calculation():
    """保留比例计算：总资金10万保留20%，可投8万"""
    strategy = _create_strategy()
    investable = strategy.calc_investable_amount(100000)
    assert investable == 80000


def test_reverse_repo_select_code_sh():
    """资金>=10万且优先沪市时选择沪市品种204001"""
    strategy = _create_strategy()
    assert strategy.select_code(100000) == "204001"


def test_reverse_repo_select_code_sz():
    """资金不足10万时选择深市品种131810"""
    strategy = _create_strategy()
    assert strategy.select_code(50000) == "131810"


def test_reverse_repo_execute_on_pre_holiday():
    """节前交易日执行策略应推送通知"""
    from unittest.mock import patch

    calendar = TradingCalendar()
    calendar.add_pre_holiday(date(2026, 9, 30), "国庆节前")
    # amount=150000，保留20%后可投120000>=10万，选择沪市品种
    config = {
        "enabled": True,
        "min_rate": 3.0,
        "reserve_ratio": 0.2,
        "amount": 150000,
        "prefer_sh": True,
    }
    strategy = _create_strategy(config=config, calendar=calendar)

    with patch('strategies.reverse_repo.date') as mock_date:
        mock_date.today.return_value = date(2026, 9, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        strategy.execute()

    # 验证通知被调用
    strategy._notifier.notify.assert_called_once()
    call_args = strategy._notifier.notify.call_args
    assert call_args.args[0] == "逆回购操作提醒"
    assert "204001" in call_args.args[1]
    assert "120000" in call_args.args[1]
    assert call_args.kwargs.get("event_type") == "reverse_repo" or \
           (len(call_args.args) > 2 and call_args.args[2] == "reverse_repo")


def test_reverse_repo_execute_on_normal_day():
    """普通交易日执行策略不应推送通知"""
    from unittest.mock import patch

    strategy = _create_strategy()

    with patch('strategies.reverse_repo.date') as mock_date:
        mock_date.today.return_value = date(2026, 4, 29)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        strategy.execute()

    strategy._notifier.notify.assert_not_called()


def test_reverse_repo_select_code_sz_when_not_prefer_sh():
    """不优先沪市时即使资金充足也选择深市品种"""
    config = {
        "enabled": True,
        "prefer_sh": False,
        "reserve_ratio": 0.2,
        "amount": 100000,
    }
    strategy = _create_strategy(config=config)
    assert strategy.select_code(100000) == "131810"


def test_reverse_repo_today_updates_on_execute():
    """验证execute方法中_today会重新获取当天日期，不依赖构造时的固定值"""
    from unittest.mock import patch

    calendar = TradingCalendar()
    calendar.add_pre_holiday(date(2026, 9, 30), "国庆节前")
    strategy = _create_strategy(calendar=calendar)
    # 构造时设置一个旧日期
    strategy._today = date(2026, 1, 1)
    # execute时应重新获取date.today()
    strategy.execute()
    # 非节前日，不应通知。关键验证：_today被更新了
    with patch('strategies.reverse_repo.date') as mock_date:
        mock_date.today.return_value = date(2026, 9, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        strategy.execute()
        strategy._notifier.notify.assert_called_once()
