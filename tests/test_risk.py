# -*- coding: utf-8 -*-
"""风控检查模块单元测试"""

from trader.risk import RiskChecker


def test_check_daily_trade_limit():
    """测试每日交易次数限制"""
    checker = RiskChecker(max_daily_trades_per_fund=1)
    checker._daily_trade_count["164906"] = 1
    assert checker.check_daily_limit("164906") is False
    assert checker.check_daily_limit("164907") is True


def test_check_hard_stop_loss():
    """测试硬止损线检查"""
    checker = RiskChecker(hard_stop_loss=5.0)
    assert checker.check_stop_loss(-4.0) is True
    assert checker.check_stop_loss(-6.0) is False


def test_check_single_trade_ratio():
    """测试单笔交易占比限制"""
    checker = RiskChecker(max_single_trade_ratio=0.3)
    assert checker.check_trade_ratio(20000, 100000) is True
    assert checker.check_trade_ratio(40000, 100000) is False


def test_check_trade_ratio_zero_funds():
    """测试总资金为零时的交易占比检查"""
    checker = RiskChecker(max_single_trade_ratio=0.3)
    assert checker.check_trade_ratio(1000, 0) is False


def test_reset_daily():
    """测试每日交易计数重置"""
    checker = RiskChecker()
    checker.record_trade("164906")
    checker.reset_daily()
    assert checker.check_daily_limit("164906") is True
