from strategies.lof_premium.filter import LofFilter


def test_filter_volume():
    f = LofFilter(min_volume=500)
    assert f.filter_by_volume(1200.0) is True
    assert f.filter_by_volume(300.0) is False


def test_filter_suspended():
    f = LofFilter()
    assert f.filter_by_suspension(True) is False
    assert f.filter_by_suspension(False) is True


def test_filter_attribute_name_matches_sub_obj_map():
    """LofFilter的属性名必须与STRATEGY_SUB_OBJ_MAP中映射一致"""
    from config_manager import STRATEGY_SUB_OBJ_MAP
    # STRATEGY_SUB_OBJ_MAP中lof_premium._filter映射了_min_volume
    filter_attrs = STRATEGY_SUB_OBJ_MAP["lof_premium"]["_filter"]
    assert "_min_volume" in filter_attrs
    # LofFilter实例应有_min_volume属性
    f = LofFilter(min_volume=500)
    assert hasattr(f, "_min_volume"), "LofFilter must have _min_volume attribute"
    assert f._min_volume == 500
