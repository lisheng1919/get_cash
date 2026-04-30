from notify.base import Notifier, NotificationManager, NotificationEvent


def test_notifier_base_send_raises():
    n = Notifier()
    try:
        n.send("test", "test message")
        assert False, "应抛出NotImplementedError"
    except NotImplementedError:
        pass


def test_notification_manager_dispatch():
    received = []

    class MockNotifier(Notifier):
        name = "mock"

        def send(self, title: str, message: str) -> bool:
            received.append((title, message))
            return True

    mgr = NotificationManager({"desktop": {"enabled": True}}, dual_channel_events=["bond_winning"])
    mgr.register("mock", MockNotifier())
    mgr.notify("test", "hello", event_type="bond_winning")
    assert len(received) == 1
    assert received[0] == ("test", "hello")


def test_notification_manager_disabled():
    received = []

    class MockNotifier(Notifier):
        name = "mock"

        def send(self, title: str, message: str) -> bool:
            received.append((title, message))
            return True

    mgr = NotificationManager({"mock": {"enabled": False}})
    mgr.register("mock", MockNotifier())
    mgr.notify("test", "hello")
    assert len(received) == 0


def test_notification_event_enum():
    """验证新增的事件枚举值"""
    assert NotificationEvent.LOF_PREMIUM.value == "lof_premium"
    assert NotificationEvent.BOND_IPO.value == "bond_ipo"
    assert NotificationEvent.REVERSE_REPO.value == "reverse_repo"
    assert NotificationEvent.BOND_ALLOCATION.value == "bond_allocation"


def test_notification_manager_with_storage():
    import sqlite3
    from data.models import init_db
    from data.storage import Storage

    conn = sqlite3.Connection(":memory:")
    init_db(conn)
    storage = Storage(conn)

    class MockNotifier(Notifier):
        name = "mock"
        def send(self, title: str, message: str) -> bool:
            return True

    class FailNotifier(Notifier):
        name = "fail_channel"
        def send(self, title: str, message: str) -> bool:
            raise RuntimeError("发送失败")

    mgr = NotificationManager(
        {"mock": {"enabled": True}, "fail_channel": {"enabled": True}},
        storage=storage,
    )
    mgr.register("mock", MockNotifier())
    mgr.register("fail_channel", FailNotifier())

    mgr.notify("测试标题", "测试内容", event_type="lof_premium")

    logs = storage.list_notification_logs()
    assert len(logs) == 2
    channels = {log["channel"]: log["status"] for log in logs}
    assert channels["mock"] == "success"
    assert channels["fail_channel"] == "fail"

    conn.close()


def test_notification_manager_no_storage():
    """不注入storage时不报错"""
    class MockNotifier(Notifier):
        name = "mock"
        def send(self, title: str, message: str) -> bool:
            return True

    mgr = NotificationManager({"mock": {"enabled": True}})
    mgr.register("mock", MockNotifier())
    mgr.notify("测试", "内容")
