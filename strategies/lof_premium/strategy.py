"""LOF溢价率套利策略，检测溢价机会并推送通知"""

import logging
from datetime import datetime

from strategies.base import BaseStrategy
from strategies.lof_premium.premium import PremiumCalculator
from strategies.lof_premium.filter import LofFilter
from strategies.lof_premium.signal import SignalGenerator

logger = logging.getLogger(__name__)


class LofPremiumStrategy(BaseStrategy):
    """LOF溢价率套利策略

    轮询LOF基金列表，计算溢价率，通过过滤和信号防抖后
    推送套利通知。支持可选自动交易模式。
    """

    name: str = "lof_premium"

    def __init__(self, config: dict, storage, notifier):
        """初始化LOF溢价策略

        Args:
            config: 策略配置字典，支持以下键：
                - enabled: 是否启用，默认True
                - premium_threshold: 实时IOPV溢价阈值(%), 默认2.0
                - low_precision_threshold: 非实时IOPV溢价阈值(%), 默认3.0
                - min_volume: 最低日成交量(万元), 默认500
                - confirm_count: 连续确认次数, 默认3
                - cooldown_minutes: 冷却期(分钟), 默认5
                - auto_trade: 是否自动交易, 默认False
            storage: 数据存储实例
            notifier: 通知管理器实例
        """
        super().__init__(config, storage, notifier)
        self._premium_calc = PremiumCalculator(
            normal_threshold=config.get("premium_threshold", 2.0),
            low_precision_threshold=config.get("low_precision_threshold", 3.0),
        )
        self._lof_filter = LofFilter(
            min_volume=config.get("min_volume", 500),
        )
        self._signal_gen = SignalGenerator(
            threshold=config.get("premium_threshold", 2.0),
            confirm_count=config.get("confirm_count", 3),
            cooldown_minutes=config.get("cooldown_minutes", 5),
        )
        self._auto_trade = config.get("auto_trade", False)

    def execute(self) -> None:
        """执行LOF溢价策略

        流程：
        1. 获取LOF基金列表
        2. 过滤停牌和低成交量基金
        3. 获取IOPV和市价
        4. 计算溢价率，与阈值比较
        5. 信号防抖判断
        6. 记录溢价历史和交易信号，推送通知
        """
        collector = getattr(self, "_collector", None)
        if collector is None:
            logger.info("LOF溢价策略：未注入数据采集器，跳过执行")
            return

        # 1. 获取LOF基金列表
        try:
            fund_list = collector.fetch_lof_fund_list()
        except Exception as ex:
            logger.error("获取LOF基金列表失败: %s", ex)
            return

        if not fund_list:
            logger.info("LOF溢价策略：无基金数据")
            return

        # 2. 过滤停牌和低成交量
        active_funds = []
        for fund in fund_list:
            if not self._lof_filter.filter_by_suspension(fund.get("is_suspended", False)):
                continue
            if not self._lof_filter.filter_by_volume(fund.get("daily_volume", 0.0)):
                continue
            active_funds.append(fund)

        if not active_funds:
            logger.info("LOF溢价策略：过滤后无活跃基金")
            return

        # 3. 获取IOPV和市价
        codes = [f["code"] for f in active_funds]
        try:
            iopv_data = collector.fetch_lof_iopv(codes)
        except Exception as ex:
            logger.error("获取IOPV数据失败: %s", ex)
            return

        try:
            realtime_data = collector.fetch_lof_realtime(codes)
        except Exception as ex:
            logger.error("获取实时行情失败: %s", ex)
            return

        # 4. 计算溢价率并判断信号
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for fund in active_funds:
            code = fund["code"]
            iopv_info = iopv_data.get(code, {})
            iopv = iopv_info.get("iopv", 0.0)
            iopv_source = iopv_info.get("iopv_source", "estimated")
            price = realtime_data.get(code, {}).get("price", 0.0)

            if iopv <= 0 or price <= 0:
                continue

            # 计算溢价率
            premium_rate = self._premium_calc.calculate(price, iopv)
            threshold = self._premium_calc.get_threshold(iopv_source)

            # 记录溢价历史（无论是否超过阈值）
            self._storage.insert_premium_history(
                timestamp=now,
                fund_code=code,
                price=price,
                iopv=iopv,
                premium_rate=premium_rate,
                iopv_source=iopv_source,
            )

            # 溢价率未达阈值，跳过信号判断
            if premium_rate < threshold:
                continue

            # 信号防抖判断
            signal = self._signal_gen.check(code, premium_rate)
            if signal is None:
                continue

            # 5. 生成信号，入库并通知
            logger.info(
                "LOF溢价信号: %s 溢价率%.2f%% (阈值%.2f%%)",
                code, premium_rate, threshold,
            )

            self._storage.insert_trade_signal(
                trigger_time=now,
                fund_code=code,
                premium_rate=premium_rate,
                action="sell_and_subscribe",
                status="pending",
                iopv_source=iopv_source,
            )

            self.notify(
                title="LOF溢价套利信号",
                message=f"{code} {fund.get('name', '')} 溢价率{premium_rate:.2f}%（阈值{threshold:.1f}%）",
                event_type="lof_premium",
            )

            # 自动交易预留（当前版本不实际调用）
            if self._auto_trade:
                logger.info("自动交易已启用，但TradeExecutor尚未接入，跳过执行")
