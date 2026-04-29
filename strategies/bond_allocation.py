"""可转债配债策略，基于保守估值计算安全垫并避让抢权风险"""

import logging

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class BondAllocationStrategy(BaseStrategy):
    """可转债配债策略

    通过保守估值模型计算配债安全垫，筛选高含权低风险标的，
    同时避让ST/退市股和抢权过热的正股。
    """

    name: str = "bond_allocation"

    def __init__(self, config: dict, storage, notifier):
        """初始化可转债配债策略

        Args:
            config: 策略配置字典，支持以下键：
                - enabled: 是否启用，默认True
                - min_content_weight: 最低含权量(%)，默认20
                - min_safety_cushion: 最低安全垫(%), 默认5.0
                - conservative_factor: 保守系数，默认0.8
                - rush_warning_threshold: 抢权预警阈值(%), 默认5.0
            storage: 数据存储实例
            notifier: 通知管理器实例
        """
        super().__init__(config, storage, notifier)
        self._min_content_weight = config.get("min_content_weight", 20)
        self._min_safety_cushion = config.get("min_safety_cushion", 5.0)
        self._conservative_factor = config.get("conservative_factor", 0.8)
        self._rush_threshold = config.get("rush_warning_threshold", 5.0)

    def calc_safety_cushion(self, stock_price: float, content_weight: float,
                            avg_opening_premium: float) -> float:
        """计算配债安全垫

        基于保守估值模型：将历史平均上市溢价乘以保守系数，
        估算配债收益占正股投入的比例。

        Args:
            stock_price: 正股价格(元)
            content_weight: 百股含权量(%)
            avg_opening_premium: 历史平均上市溢价(如0.30表示30%)

        Returns:
            安全垫百分比，如6.0表示6%
        """
        # 保守估值：上市价格 = 面值 * (1 + 平均溢价 * 保守系数)
        estimated_listing_price = 100 * (1 + avg_opening_premium * self._conservative_factor)
        # 每百元正股对应的配债收益
        estimated_profit = (estimated_listing_price - 100) * content_weight / 100
        # 正股投入成本
        stock_invest = stock_price * 100
        if stock_invest <= 0:
            return 0.0
        # 安全垫 = 配债收益 / 正股投入 * 100
        return estimated_profit / stock_invest * 100

    def is_rush_warning(self, stock_rise_pct: float) -> bool:
        """判断正股是否触发抢权预警

        正股涨幅过大时，配债后正股下跌风险加剧，
        需要避让抢权行情。

        Args:
            stock_rise_pct: 正股近期涨幅百分比

        Returns:
            True表示触发抢权预警，False表示安全
        """
        return stock_rise_pct >= self._rush_threshold

    def is_stock_excluded(self, stock_name: str) -> bool:
        """判断正股是否应被排除

        ST、*ST及退市股基本面风险极高，不参与配债。

        Args:
            stock_name: 股票名称

        Returns:
            True表示应排除，False表示可参与
        """
        exclude_prefixes = ("ST", "*ST", "退市")
        return any(stock_name.startswith(p) for p in exclude_prefixes)

    def execute(self) -> None:
        """执行可转债配债策略

        流程：
        1. 获取即将发行转债的标的列表
        2. 排除ST/退市股
        3. 计算安全垫，筛选达标标的
        4. 检查抢权预警
        5. 推送符合条件的配债机会通知
        """
        logger.info("可转债配债：检查即将发行转债...")
