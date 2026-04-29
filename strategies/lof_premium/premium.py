# -*- coding: utf-8 -*-
"""LOF溢价率计算模块"""


class PremiumCalculator:
    """LOF基金溢价率计算器

    根据市价与IOPV（基金净值）计算溢价率，并根据IOPV数据来源
    返回对应的溢价率阈值（实时IOPV精度高，阈值可更低）。
    """

    def __init__(self, normal_threshold=2.0, low_precision_threshold=3.0):
        """
        Args:
            normal_threshold: 实时IOPV对应的溢价率阈值（%）
            low_precision_threshold: 非实时IOPV对应的溢价率阈值（%）
        """
        self.normal_threshold = normal_threshold
        self.low_precision_threshold = low_precision_threshold

    def calculate(self, price, iopv):
        """计算溢价率

        Args:
            price: LOF基金市价
            iopv: 基金实时净值（IOPV）

        Returns:
            溢价率（%），iopv<=0时返回0.0
        """
        if iopv <= 0:
            return 0.0
        return (price - iopv) / iopv * 100

    def get_threshold(self, iopv_source):
        """根据IOPV数据来源获取对应的溢价率阈值

        Args:
            iopv_source: IOPV数据来源，"realtime"表示实时数据

        Returns:
            对应的溢价率阈值（%）
        """
        if iopv_source == "realtime":
            return self.normal_threshold
        return self.low_precision_threshold
