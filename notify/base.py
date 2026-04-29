# 通知层基础定义
from enum import Enum
from typing import Dict, List, Optional


class NotificationEvent(str, Enum):
    """通知事件类型枚举"""
    BOND_WINNING = "bond_winning"
    BOND_ALLOCATION_ACTION = "bond_allocation_action"
    LISTING_SELL = "listing_sell"
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

    def __init__(self, config: dict, dual_channel_events: Optional[List[str]] = None):
        """
        初始化通知管理器

        :param config: 各通知渠道配置，格式如 {"desktop": {"enabled": True}, "wechat": {"enabled": False}}
        :param dual_channel_events: 需要双渠道通知的事件类型列表
        """
        self._config = config
        self._dual_channel_events = dual_channel_events or []
        self._notifiers: Dict[str, Notifier] = {}

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
            except Exception:
                # 单个渠道发送失败不影响其他渠道
                pass
