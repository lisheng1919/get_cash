from notify.base import Notifier, NotificationManager


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
