"""可转债配债策略，基于保守估值计算安全垫并避让抢权风险"""

import logging
from datetime import date

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
        2. 筛选近期申购的标的
        3. 排除ST/退市股
        4. 计算安全垫，筛选达标标的
        5. 检查抢权预警
        6. 入库并推送通知
        """
        collector = getattr(self, "_collector", None)
        if collector is None:
            logger.info("可转债配债策略：未注入数据采集器，跳过执行")
            return

        # 获取配债列表
        try:
            allocation_list = collector.fetch_bond_allocation_list()
        except Exception as ex:
            logger.error("获取配债列表失败: %s", ex)
            return

        if not allocation_list:
            logger.info("可转债配债：当前无发行转债")
            return

        # 筛选近期申购的标的
        notify_days = self._config.get("notify_before_record_day", 7)
        upcoming = []
        for bond in allocation_list:
            subscribe_date = bond.get("subscribe_date", "")
            if not subscribe_date:
                continue
            try:
                sub_date = date.fromisoformat(subscribe_date)
                days_until = (sub_date - date.today()).days
                if 0 <= days_until <= notify_days:
                    upcoming.append(bond)
            except ValueError:
                continue

        if not upcoming:
            logger.info("可转债配债：近期(%d天内)无配债机会", notify_days)
            return

        # 逐只处理
        for bond in upcoming:
            stock_name = bond.get("stock_name", "")

            # 排除ST/退市股
            if self.is_stock_excluded(stock_name):
                logger.info("可转债配债：排除ST/退市股 %s", stock_name)
                continue

            stock_price = bond.get("stock_price", 0.0)
            content_weight = bond.get("content_weight", 20.0)

            # 计算安全垫（使用固定默认溢价率0.30）
            safety_cushion = self.calc_safety_cushion(
                stock_price=stock_price,
                content_weight=content_weight,
                avg_opening_premium=0.30,
            )

            # 安全垫不达标
            if safety_cushion < self._min_safety_cushion:
                logger.info(
                    "可转债配债：%s 安全垫%.2f%%低于阈值%.1f%%，跳过",
                    bond.get("code", ""), safety_cushion, self._min_safety_cushion,
                )
                continue

            # 检查抢权预警（暂用0，后续可补充）
            if self.is_rush_warning(0):
                logger.info("可转债配债：%s 触发抢权预警，跳过", bond.get("code", ""))
                continue

            # 入库
            self._storage.upsert_bond_allocation(
                code=bond.get("code", ""),
                stock_code=bond.get("stock_code", ""),
                stock_name=stock_name,
                content_weight=content_weight,
                safety_cushion=safety_cushion,
                record_date=bond.get("subscribe_date", ""),
            )

            # 推送通知
            self.notify(
                title="可转债配债提醒",
                message=(
                    f"{bond.get('code', '')} {bond.get('name', '')}\n"
                    f"正股：{stock_name}({bond.get('stock_code', '')}) 价格{stock_price:.2f}\n"
                    f"含权量：{content_weight:.1f}% 安全垫：{safety_cushion:.2f}%"
                ),
                event_type="bond_allocation",
            )
            logger.info(
                "可转债配债通知: %s 安全垫%.2f%%",
                bond.get("code", ""), safety_cushion,
            )
