# 微信通知器（Server酱）
import requests

from notify.base import Notifier


class WechatNotifier(Notifier):
    """使用 Server酱 发送微信通知"""
    name = "wechat"

    def __init__(self, serverchan_key: str):
        """
        初始化微信通知器

        :param serverchan_key: Server酱的SendKey
        """
        self._serverchan_key = serverchan_key

    def send(self, title: str, message: str) -> bool:
        """
        通过Server酱发送微信通知

        :param title: 通知标题
        :param message: 通知内容
        :return: 发送成功返回True，异常返回False
        """
        try:
            url = f"https://sctapi.ftqq.com/{self._serverchan_key}.send"
            resp = requests.post(url, data={"title": title, "desp": message}, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
