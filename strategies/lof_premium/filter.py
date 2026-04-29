# -*- coding: utf-8 -*-
"""LOF基金过滤条件模块"""


class LofFilter:
    """LOF基金过滤器

    根据成交量和停牌状态过滤不符合条件的基金。
    """

    def __init__(self, min_volume=500.0):
        """
        Args:
            min_volume: 最低日成交量（万元），低于此值的基金被过滤
        """
        self.min_volume = min_volume

    def filter_by_volume(self, daily_volume):
        """按成交量过滤

        Args:
            daily_volume: 日成交量（万元）

        Returns:
            True表示通过过滤，False表示被过滤掉
        """
        return daily_volume >= self.min_volume

    def filter_by_suspension(self, is_suspended):
        """按停牌状态过滤

        Args:
            is_suspended: 是否停牌

        Returns:
            True表示通过过滤（未停牌），False表示被过滤掉（已停牌）
        """
        return not is_suspended
