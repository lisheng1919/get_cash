# 通知层基础定义
from enum import Enum
from typing import Dict, List, Optional


class NotificationEvent(str, Enum):
    """通知事件类型枚举"""
    BOND_WINNING = "bond_winning"
    BOND_ALLOCATION_ACTION = "bond_allocation_action"
    LISTING_SELL = "listing_sell"
    LOF_PREMIUM = "lof_premium"
    BOND_IPO = "bond_ipo"
    REVERSE_REPO = "reverse_repo"
    BOND_ALLOCATION = "bond_allocation"
    DATA_SOURCE_FAILURE = "data_source_failure"
    DEFAULT = "default"


class Notifier:
    """通知器基类"""
    name: str = "base"

    def send(self, title: str, message: str) -> bool:
        """发送通知，子类必须实现"""
        raise NotImplementedError


class NotificationManager:
    """通知管理器：负责注册和分发通知"""

    def __init__(self, config: dict, dual_channel_events: Optional[List[str]] = None,
                 storage=None):
        """
        初始化通知管理器

        :param config: 各通知渠道配置，格式如 {"desktop": {"enabled": True}, "wechat": {"enabled": False}}
        :param dual_channel_events: 需要双渠道通知的事件类型列表
        :param storage: Storage实例，用于持久化通知记录
        """
        self._config = config
        self._dual_channel_events = dual_channel_events or []
        self._notifiers: Dict[str, Notifier] = {}
        self._storage = storage

    def register(self, name: str, notifier: Notifier) -> None:
        """注册通知器"""
        self._notifiers[name] = notifier

    def notify(self, title: str, message: str, event_type: str = "default") -> None:
        """
        向所有已注册且启用的通知渠道发送通知

        :param title: 通知标题
        :param message: 通知内容
        :param event_type: 事件类型，用于判断是否需要双渠道通知
        """
        for name, notifier in self._notifiers.items():
            # 检查该渠道是否启用
            channel_config = self._config.get(name, {})
            if not channel_config.get("enabled", True):
                continue
            try:
                notifier.send(title, message)
                self._log_notification(name, event_type, title, message, "success")
            except Exception as ex:
                self._log_notification(name, event_type, title, message, "fail")
                import logging
                logging.getLogger(__name__).warning("通知渠道%s发送失败: %s", name, ex)

    def _log_notification(self, channel: str, event_type: str,
                          title: str, message: str, status: str) -> None:
        """持久化通知发送记录"""
        if self._storage is None:
            return
        try:
            self._storage.insert_notification_log(channel, event_type, title, message, status)
        except Exception:
            pass
