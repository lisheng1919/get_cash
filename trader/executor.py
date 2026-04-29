# -*- coding: utf-8 -*-
"""交易执行模块 - LOF基金套利的卖出与申购执行"""

import logging

logger = logging.getLogger(__name__)


class TradeExecutor:
    """交易执行器，封装miniQMT的xtquant交易接口"""

    def __init__(self, xt_trader=None):
        """初始化交易执行器

        Args:
            xt_trader: miniQMT的xtquant交易对象，测试环境可传None
        """
        self._xt = xt_trader

    def sell_lof(self, fund_code: str, shares: int) -> bool:
        """卖出LOF基金份额（市价单）

        Args:
            fund_code: 基金代码
            shares: 卖出份额

        Returns:
            True 表示下单成功，False 表示下单失败或xt_trader未初始化
        """
        if self._xt is None:
            logger.warning("xt_trader未初始化，无法执行卖出操作: fund_code=%s, shares=%d", fund_code, shares)
            return False

        try:
            # 调用xtquant下单接口：市价单、方向=2(卖出)、类型=2(市价)
            self._xt.order_stock(fund_code, 2, shares, 2)
            logger.info("卖出下单成功: fund_code=%s, shares=%d", fund_code, shares)
            return True
        except Exception as e:
            logger.error("卖出下单异常: fund_code=%s, shares=%d, error=%s", fund_code, shares, e)
            return False

    def subscribe_lof(self, fund_code: str, amount: float) -> bool:
        """申购LOF基金

        Args:
            fund_code: 基金代码
            amount: 申购金额

        Returns:
            True 表示下单成功，False 表示下单失败或xt_trader未初始化
        """
        if self._xt is None:
            logger.warning("xt_trader未初始化，无法执行申购操作: fund_code=%s, amount=%.2f", fund_code, amount)
            return False

        try:
            # 调用xtquant基金申购接口
            self._xt.order_fund(fund_code, amount)
            logger.info("申购下单成功: fund_code=%s, amount=%.2f", fund_code, amount)
            return True
        except Exception as e:
            logger.error("申购下单异常: fund_code=%s, amount=%.2f, error=%s", fund_code, amount, e)
            return False

    def execute_lof_arbitrage(self, fund_code: str, shares: int, amount: float) -> dict:
        """执行LOF套利：先卖出再申购

        执行顺序保护：卖出成功后才执行申购，避免申购后无法卖出的风险。
        若卖出成功但申购失败，需人工介入处理（已持有现金但未完成申购）。

        Args:
            fund_code: 基金代码
            shares: 卖出份额
            amount: 申购金额

        Returns:
            执行结果字典:
            - 全部成功: {"success": True, "fund_code": fund_code}
            - 卖出失败: {"success": False, "step": "sell", "error": "卖出失败"}
            - 卖出成功但申购失败: {"success": False, "step": "subscribe", "error": "申购失败，卖出已成功，需人工介入"}
        """
        # 第一步：先卖出
        sell_ok = self.sell_lof(fund_code, shares)
        if not sell_ok:
            return {"success": False, "step": "sell", "error": "卖出失败"}

        # 第二步：卖出成功后再申购
        subscribe_ok = self.subscribe_lof(fund_code, amount)
        if not subscribe_ok:
            # 卖出已成功但申购失败，需人工介入
            logger.error("LOF套利部分失败: 卖出成功但申购失败, fund_code=%s, 需人工介入", fund_code)
            return {"success": False, "step": "subscribe", "error": "申购失败，卖出已成功，需人工介入"}

        return {"success": True, "fund_code": fund_code}
