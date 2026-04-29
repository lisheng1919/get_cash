"""节假日逆回购策略，在节前交易日自动推送逆回购操作提醒"""

import logging
from datetime import date

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class ReverseRepoStrategy(BaseStrategy):
    """节假日逆回购策略

    在节前交易日（长假前最后一个交易日）自动提醒做逆回购，
    充分利用节假日资金占用时间获取更高收益。
    优先选择沪市品种（资金门槛10万），不足则选择深市品种。
    """

    name: str = "reverse_repo"

    def __init__(self, config: dict, storage, notifier, calendar):
        """初始化逆回购策略

        Args:
            config: 策略配置字典，支持以下键：
                - enabled: 是否启用，默认True
                - min_rate: 最低利率阈值，默认3.0
                - reserve_ratio: 资金保留比例，默认0.2
                - amount: 总资金量，默认0
                - prefer_sh: 是否优先沪市品种，默认True
            storage: 数据存储实例
            notifier: 通知管理器实例
            calendar: TradingCalendar 实例
        """
        super().__init__(config, storage, notifier)
        self._calendar = calendar
        self._min_rate = config.get("min_rate", 3.0)
        self._reserve_ratio = config.get("reserve_ratio", 0.2)
        self._amount = config.get("amount", 0)
        self._prefer_sh = config.get("prefer_sh", True)
        self._today = date.today()

    def should_trigger(self) -> bool:
        """判断今天是否应触发逆回购策略

        仅在节前交易日触发。

        Returns:
            True表示今天应执行逆回购，False表示跳过
        """
        return self._calendar.is_pre_holiday(self._today)

    def calc_investable_amount(self, total_funds: float) -> float:
        """计算可投入逆回购的资金金额

        扣除保留资金后，剩余部分可用于逆回购。

        Args:
            total_funds: 总资金

        Returns:
            可投入逆回购的金额
        """
        return total_funds * (1 - self._reserve_ratio)

    def select_code(self, funds: float) -> str:
        """根据资金量选择逆回购品种

        优先选择沪市1天逆回购（204001），资金门槛10万；
        资金不足10万或未优先沪市时选择深市1天逆回购（131810）。

        Args:
            funds: 可投入资金

        Returns:
            逆回购品种代码
        """
        if self._prefer_sh and funds >= 100000:
            return "204001"
        return "131810"

    def execute(self) -> None:
        """执行逆回购策略

        流程：
        1. 判断今天是否为节前交易日，不是则跳过
        2. 计算可投入逆回购的资金
        3. 选择合适的逆回购品种
        4. 获取节假日名称
        5. 构建通知消息并推送
        """
        if not self.should_trigger():
            logger.info("今日(%s)非节前交易日，跳过逆回购策略", self._today)
            return

        # 计算可投金额
        investable = self.calc_investable_amount(self._amount)

        # 选择品种
        code = self.select_code(investable)
        market_label = "沪市" if code == "204001" else "深市"

        # 获取节假日名称
        upcoming = self._calendar.get_upcoming_pre_holidays(self._today)
        holiday_name = upcoming[0][1] if upcoming else "节假日"

        # 构建通知消息
        message = (
            f"{holiday_name}前最后交易日，建议做逆回购\n"
            f"品种：{market_label} {code}\n"
            f"可投金额：{investable:.0f}元"
        )

        self.notify(
            title="逆回购操作提醒",
            message=message,
            event_type="reverse_repo",
        )
        logger.info("已推送逆回购通知: %s %s，可投金额%.0f元", market_label, code, investable)
