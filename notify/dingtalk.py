# 钉钉通知器
import requests

from notify.base import Notifier


class DingtalkNotifier(Notifier):
    """使用钉钉Webhook发送通知"""
    name = "dingtalk"

    def __init__(self, webhook: str):
        """
        初始化钉钉通知器

        :param webhook: 钉钉机器人Webhook地址
        """
        self._webhook = webhook

    def send(self, title: str, message: str) -> bool:
        """
        通过钉钉Webhook发送通知

        :param title: 通知标题
        :param message: 通知内容
        :return: 发送成功返回True，异常返回False
        """
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": f"### {title}\n\n{message}"
                }
            }
            resp = requests.post(
                self._webhook,
                json=payload,
                timeout=10
            )
            return resp.status_code == 200
        except Exception:
            return False
