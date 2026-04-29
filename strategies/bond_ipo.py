"""可转债打新策略，自动监控并推送可转债申购通知"""

import logging
from datetime import date

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class BondIpoStrategy(BaseStrategy):
    """可转债打新策略

    监控今日可申购的可转债，入库并推送通知。
    支持连续未中签自动暂停功能，避免无效申购。
    """

    name: str = "bond_ipo"

    def __init__(self, config: dict, storage, notifier):
        """初始化可转债打新策略

        Args:
            config: 策略配置字典，支持以下键：
                - enabled: 是否启用，默认True
                - auto_subscribe: 是否自动申购，默认True
                - max_consecutive_miss: 连续未中签暂停阈值，默认2
            storage: 数据存储实例
            notifier: 通知管理器实例
        """
        super().__init__(config, storage, notifier)
        self._auto_subscribe = config.get("auto_subscribe", True)
        self._max_miss = config.get("max_consecutive_miss", 2)
        self._consecutive_miss = 0

    def should_suspend(self) -> bool:
        """判断是否应暂停申购

        连续未中签次数达到阈值时暂停，避免无效申购。

        Returns:
            True表示应暂停，False表示继续
        """
        return self._consecutive_miss >= self._max_miss

    def get_market(self, code: str) -> str:
        """根据债券代码判断所属市场

        沪市可转债代码以"11"开头，深市以"12"开头。

        Args:
            code: 债券代码

        Returns:
            "sh"表示沪市，"sz"表示深市
        """
        if code.startswith("11"):
            return "sh"
        return "sz"

    def execute(self) -> None:
        """执行可转债打新策略

        流程：
        1. 检查是否应暂停申购
        2. 检查数据采集器是否可用
        3. 获取今日可申购转债列表
        4. 逐只入库并推送通知
        """
        # 暂停检查
        if self.should_suspend():
            logger.warning(
                "可转债打新策略已暂停：连续未中签%d次，达到阈值%d",
                self._consecutive_miss,
                self._max_miss,
            )
            return

        # 数据采集器检查
        collector = getattr(self, "_collector", None)
        if collector is None:
            logger.info("可转债打新策略：未注入数据采集器，跳过执行")
            return

        # 获取今日可申购转债列表
        today = date.today().strftime("%Y-%m-%d")
        try:
            bond_list = collector.fetch_bond_ipo_list()
        except Exception as ex:
            logger.error("获取可转债申购列表失败: %s", ex)
            return

        # 筛选今日申购的新债
        today_bonds = [
            bond for bond in bond_list
            if bond.get("subscribe_date", "") == today
        ]

        if not today_bonds:
            logger.info("今日(%s)无可申购可转债", today)
            return

        # 逐只处理：入库 + 通知
        for bond in today_bonds:
            code = bond.get("code", "")
            name = bond.get("name", "")
            subscribe_date = bond.get("subscribe_date", "")

            # 入库
            self._storage.upsert_bond_ipo(
                code=code,
                name=name,
                subscribe_date=subscribe_date,
            )

            # 推送通知
            market = self.get_market(code)
            market_label = "沪市" if market == "sh" else "深市"
            self.notify(
                title="可转债申购提醒",
                message=f"{market_label} {code} {name} 今日申购",
                event_type="bond_ipo",
            )
            logger.info("已推送可转债申购通知: %s %s (%s)", code, name, market_label)
