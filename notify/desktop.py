# 桌面通知器
from notify.base import Notifier


class DesktopNotifier(Notifier):
    """使用 plyer 发送桌面通知"""
    name = "desktop"

    def send(self, title: str, message: str) -> bool:
        """
        发送桌面通知

        :param title: 通知标题
        :param message: 通知内容
        :return: 发送成功返回True，异常返回False
        """
        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                app_name="GetCash",
                timeout=10
            )
            return True
        except Exception:
            return False
