from strategies.lof_premium.signal import SignalGenerator


def test_signal_not_triggered_below_threshold():
    gen = SignalGenerator(threshold=3.0, confirm_count=3, cooldown_minutes=5)
    assert gen.check("164906", 2.5) is None
    assert gen.check("164906", 2.8) is None


def test_signal_triggered_after_confirm_count():
    gen = SignalGenerator(threshold=3.0, confirm_count=3, cooldown_minutes=5)
    gen.check("164906", 3.5)
    gen.check("164906", 3.2)
    result = gen.check("164906", 3.8)
    assert result is not None
    assert result["fund_code"] == "164906"
    assert result["premium_rate"] == 3.8


def test_signal_cooldown():
    gen = SignalGenerator(threshold=3.0, confirm_count=1, cooldown_minutes=5)
    result1 = gen.check("164906", 3.5)
    assert result1 is not None
    result2 = gen.check("164906", 3.5)
    assert result2 is None
