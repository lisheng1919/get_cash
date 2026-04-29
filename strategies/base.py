"""策略基类，所有交易策略的抽象父类"""

from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """策略基类

    所有交易策略必须继承此类并实现 execute() 方法。
    """

    name: str = "base"

    def __init__(self, config: dict, storage, notifier):
        """初始化策略

        Args:
            config: 策略配置字典
            storage: 数据存储实例
            notifier: 通知管理器实例
        """
        self._config = config
        self._storage = storage
        self._notifier = notifier
        self._enabled = config.get("enabled", True)

    @abstractmethod
    def execute(self) -> None:
        """执行策略逻辑，子类必须实现"""

    def is_enabled(self) -> bool:
        """判断策略是否启用

        Returns:
            True表示启用，False表示禁用
        """
        return self._enabled

    def notify(self, title: str, message: str, event_type: str = "default") -> None:
        """发送通知

        Args:
            title: 通知标题
            message: 通知内容
            event_type: 事件类型，默认为 "default"
        """
        self._notifier.notify(title, message, event_type)
