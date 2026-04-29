from strategies.lof_premium.filter import LofFilter


def test_filter_volume():
    f = LofFilter(min_volume=500)
    assert f.filter_by_volume(1200.0) is True
    assert f.filter_by_volume(300.0) is False


def test_filter_suspended():
    f = LofFilter()
    assert f.filter_by_suspension(True) is False
    assert f.filter_by_suspension(False) is True
