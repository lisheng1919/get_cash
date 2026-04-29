# -*- coding: utf-8 -*-
"""风控检查模块 - 交易前的风险控制校验"""

import logging

logger = logging.getLogger(__name__)


class RiskChecker:
    """风控检查器，提供交易前的各类风控校验"""

    def __init__(self, max_daily_trades_per_fund=1, max_single_trade_ratio=0.3, hard_stop_loss=5.0):
        """初始化风控参数

        Args:
            max_daily_trades_per_fund: 每只基金每日最大交易次数
            max_single_trade_ratio: 单笔交易占总额的最大比例
            hard_stop_loss: 硬止损线（百分比，如5.0表示5%）
        """
        self._max_daily_trades_per_fund = max_daily_trades_per_fund
        self._max_single_trade_ratio = max_single_trade_ratio
        self._hard_stop_loss = hard_stop_loss
        # 每日交易计数：基金代码 -> 已交易次数
        self._daily_trade_count = {}

    def check_daily_limit(self, fund_code: str) -> bool:
        """检查基金当日交易次数是否已达上限

        Args:
            fund_code: 基金代码

        Returns:
            True 表示未达上限可以交易，False 表示已达上限
        """
        current_count = self._daily_trade_count.get(fund_code, 0)
        return current_count < self._max_daily_trades_per_fund

    def record_trade(self, fund_code: str) -> None:
        """记录一次交易，计数+1

        Args:
            fund_code: 基金代码
        """
        self._daily_trade_count[fund_code] = self._daily_trade_count.get(fund_code, 0) + 1

    def check_trade_ratio(self, trade_amount: float, total_funds: float) -> bool:
        """检查单笔交易金额占比是否超过限制

        Args:
            trade_amount: 交易金额
            total_funds: 总资金

        Returns:
            True 表示占比合规，False 表示占比超限或总资金为零
        """
        # 总资金为零时无法计算比例，拒绝交易
        if total_funds == 0:
            return False
        return trade_amount / total_funds <= self._max_single_trade_ratio

    def check_stop_loss(self, current_loss_pct: float) -> bool:
        """检查当前亏损是否触及硬止损线

        Args:
            current_loss_pct: 当前亏损百分比（负数表示亏损）

        Returns:
            True 表示未触及止损线，False 表示已触及应停止交易
        """
        return abs(current_loss_pct) < self._hard_stop_loss

    def reset_daily(self) -> None:
        """重置每日交易计数，通常在每日开盘前调用"""
        self._daily_trade_count = {}
