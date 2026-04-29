# -*- coding: utf-8 -*-
"""LOF溢价率信号生成与防抖模块"""

import time
from typing import Dict, Optional


class SignalGenerator:
    """溢价率信号生成器

    当溢价率连续达到阈值时生成套利信号，支持确认次数和冷却期防抖。
    """

    def __init__(self, threshold=3.0, confirm_count=3, cooldown_minutes=5):
        """
        Args:
            threshold: 溢价率阈值（%），超过此值才计入确认
            confirm_count: 连续确认次数，达到后触发信号
            cooldown_minutes: 冷却期（分钟），同一基金两次信号的最小间隔
        """
        self.threshold = threshold
        self.confirm_count = confirm_count
        self.cooldown_seconds = cooldown_minutes * 60
        # 每只基金的连续确认计数
        self._consecutive = {}
        # 每只基金的上次信号时间
        self._last_signal_time = {}

    def check(self, fund_code, premium_rate):
        """检查溢价率并决定是否生成信号

        逻辑：
        1. 溢价率 < 阈值 → 重置该基金连续计数，返回None
        2. 溢价率 >= 阈值但连续次数未达confirm_count → 计数+1，返回None
        3. 连续次数达到confirm_count但在冷却期内 → 返回None
        4. 连续次数达到confirm_count且冷却期外 → 重置计数，记录时间，返回信号

        Args:
            fund_code: 基金代码
            premium_rate: 当前溢价率（%）

        Returns:
            信号字典或None
        """
        count = self._consecutive.get(fund_code, 0)

        # 溢价率未达阈值，重置计数
        if premium_rate < self.threshold:
            self._consecutive[fund_code] = 0
            return None

        # 溢价率达到阈值，连续计数+1
        count += 1
        self._consecutive[fund_code] = count

        # 未达确认次数
        if count < self.confirm_count:
            return None

        # 达到确认次数，检查冷却期
        now = time.time()
        last_time = self._last_signal_time.get(fund_code, 0)
        if now - last_time < self.cooldown_seconds:
            return None

        # 冷却期外，生成信号
        self._consecutive[fund_code] = 0
        self._last_signal_time[fund_code] = now
        return {
            "fund_code": fund_code,
            "premium_rate": premium_rate,
            "threshold": self.threshold,
        }
