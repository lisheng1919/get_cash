from strategies.lof_premium.premium import PremiumCalculator


def test_premium_rate_calculation():
    calc = PremiumCalculator()
    rate = calc.calculate(1.102, 1.065)
    expected = (1.102 - 1.065) / 1.065 * 100
    assert abs(rate - expected) < 0.01


def test_premium_rate_zero_iopv():
    calc = PremiumCalculator()
    assert calc.calculate(1.102, 0) == 0.0


def test_threshold_adjustment():
    calc = PremiumCalculator(low_precision_threshold=3.0, normal_threshold=2.0)
    assert calc.get_threshold("realtime") == 2.0
    assert calc.get_threshold("estimated") == 3.0
