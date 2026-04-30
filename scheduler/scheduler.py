"""策略调度器，基于 APScheduler 实现定时任务管理"""

import logging
import time
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from scheduler.calendar import TradingCalendar
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyScheduler:
    """策略调度器

    管理策略的注册与定时执行，支持每日定时任务和间隔任务。
    每日任务自动判断是否为交易日，非交易日跳过执行。
    """

    def __init__(self, calendar: TradingCalendar, storage=None, slow_threshold_ms: int = 30000):
        """初始化调度器

        Args:
            calendar: 交易日历实例，用于判断是否为交易日
            storage: 数据存储实例，用于记录执行日志和告警事件
            slow_threshold_ms: 慢执行阈值（毫秒），超过则产生告警
        """
        self._scheduler = BlockingScheduler()
        self._calendar = calendar
        self._storage = storage
        self._slow_threshold_ms = slow_threshold_ms
        self._strategies = {}  # type: dict[str, BaseStrategy]
        self._heartbeat_interval = 300  # 默认5分钟

    def register(self, strategy: BaseStrategy) -> None:
        """注册策略

        Args:
            strategy: 策略实例
        """
        self._strategies[strategy.name] = strategy
        logger.info("策略已注册: %s (enabled=%s)", strategy.name, strategy.is_enabled())

    def add_daily_job(self, strategy_name: str, hour: int, minute: int) -> None:
        """添加每日定时任务

        仅在交易日（周一至周五且非节假日）执行策略。
        非交易日自动跳过，并记录日志。

        Args:
            strategy_name: 策略名称
            hour: 执行小时（24小时制）
            minute: 执行分钟

        Raises:
            ValueError: 策略未注册或策略未启用
        """
        strategy = self._get_strategy(strategy_name)

        # 包装函数：先判断交易日，再执行策略，记录执行日志和告警
        def _daily_wrapper():
            today = date.today()
            if not self._calendar.is_trading_day(today):
                logger.info("非交易日，跳过策略 [%s] 执行: %s", strategy_name, today)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "skip", 0, "非交易日")
                return
            logger.info("交易日，执行策略 [%s]: %s", strategy_name, today)
            start = time.perf_counter()
            try:
                strategy.execute()
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "success", duration)
            except Exception as ex:
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "fail", duration, str(ex)[:500])
                    self._storage.insert_alert_event("ERROR", strategy_name,
                                                     "策略执行失败: %s" % str(ex)[:200])
            if self._storage and duration > self._slow_threshold_ms:
                self._storage.insert_alert_event(
                    "WARN", strategy_name,
                    "策略执行耗时%dms超过阈值%dms" % (duration, self._slow_threshold_ms))

        self._scheduler.add_job(
            _daily_wrapper,
            trigger=CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute),
            name=f"daily_{strategy_name}",
        )
        logger.info("每日任务已添加: %s @ %02d:%02d", strategy_name, hour, minute)

    def add_interval_job(self, strategy_name: str, seconds: int) -> None:
        """添加间隔执行任务

        按固定秒数间隔执行策略。上一轮未完成时跳过本轮，避免任务堆积。

        Args:
            strategy_name: 策略名称
            seconds: 执行间隔（秒）

        Raises:
            ValueError: 策略未注册或策略未启用
        """
        strategy = self._get_strategy(strategy_name)

        # 包装函数：执行策略，记录执行日志和告警
        def _interval_wrapper():
            logger.info("间隔触发策略 [%s]", strategy_name)
            start = time.perf_counter()
            try:
                strategy.execute()
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "success", duration)
            except Exception as ex:
                duration = int((time.perf_counter() - start) * 1000)
                if self._storage:
                    self._storage.insert_execution_log(strategy_name, "fail", duration, str(ex)[:500])
                    self._storage.insert_alert_event("ERROR", strategy_name,
                                                     "策略执行失败: %s" % str(ex)[:200])
            if self._storage and duration > self._slow_threshold_ms:
                self._storage.insert_alert_event(
                    "WARN", strategy_name,
                    "策略执行耗时%dms超过阈值%dms" % (duration, self._slow_threshold_ms))

        self._scheduler.add_job(
            _interval_wrapper,
            trigger=IntervalTrigger(seconds=seconds),
            name=f"interval_{strategy_name}",
            max_instances=1,
            coalesce=True,
        )
        logger.info("间隔任务已添加: %s, 每 %d 秒", strategy_name, seconds)

    def add_heartbeat_job(self, interval: int = 300) -> None:
        """添加心跳定时任务，定期输出系统运行状态日志

        Args:
            interval: 心跳间隔秒数，默认300秒（5分钟）
        """
        self._heartbeat_interval = interval
        strategy_names = list(self._strategies.keys())

        def _heartbeat():
            if self._storage:
                ds_status = self._storage.list_all_data_source_status()
                unhealthy = [s for s in ds_status if s["status"] != "ok"]
                if unhealthy:
                    self._storage.insert_alert_event(
                        "WARN", "heartbeat",
                        "数据源异常: %s" % ", ".join(s["name"] for s in unhealthy))
                else:
                    self._storage.insert_alert_event("INFO", "heartbeat", "系统正常运行，数据源全部OK")
                logger.info("系统心跳：数据源 %d/%d OK，已注册策略: %s",
                            len(ds_status) - len(unhealthy), len(ds_status),
                            list(self._strategies.keys()))
            else:
                logger.info("系统心跳：正常运行中，已注册策略: %s",
                            list(self._strategies.keys()))

        self._scheduler.add_job(
            _heartbeat,
            trigger=IntervalTrigger(seconds=self._heartbeat_interval),
            name="system_heartbeat",
        )
        logger.info("心跳任务已添加，间隔 %d 秒", self._heartbeat_interval)

    def start(self) -> None:
        """启动调度器（阻塞运行）"""
        logger.info("调度器启动，已注册 %d 个策略", len(self._strategies))
        self._scheduler.start()

    def shutdown(self) -> None:
        """关闭调度器"""
        logger.info("调度器关闭")
        self._scheduler.shutdown()

    def _get_strategy(self, strategy_name: str) -> BaseStrategy:
        """获取策略实例并校验

        Args:
            strategy_name: 策略名称

        Returns:
            策略实例

        Raises:
            ValueError: 策略未注册或策略未启用
        """
        if strategy_name not in self._strategies:
            raise ValueError("策略未注册: %s" % strategy_name)
        strategy = self._strategies[strategy_name]
        if not strategy.is_enabled():
            raise ValueError("策略未启用: %s" % strategy_name)
        return strategy
