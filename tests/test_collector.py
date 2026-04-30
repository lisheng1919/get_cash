"""测试DataCollector数据采集层，含容灾切换逻辑"""

import sqlite3
from unittest.mock import patch

from data.models import init_db
from data.storage import Storage
from data.collector import DataCollector


def _create_collector(max_failures: int = 3) -> DataCollector:
    """创建内存数据库和采集器实例"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    collector = DataCollector(storage, {"max_consecutive_failures": max_failures})
    return collector


def test_collector_fallback_on_failure():
    """主源失败时应切换到备用源，返回备用源数据"""
    collector = _create_collector()

    def mock_primary_fail(*args, **kwargs):
        raise Exception("主源故障")

    def mock_fallback_ok(*args, **kwargs):
        return [{
            "code": "164906",
            "name": "测试",
            "status": "normal",
            "is_suspended": False,
            "daily_volume": 1000.0,
        }]

    with patch.object(collector, "_fetch_lof_list_primary", mock_primary_fail):
        with patch.object(collector, "_fetch_lof_list_fallback", mock_fallback_ok):
            result = collector.fetch_lof_fund_list()
            assert len(result) == 1
            assert result[0]["code"] == "164906"


def test_collector_records_failure():
    """主源和备用源均失败时，应记录数据源失败状态"""
    collector = _create_collector()

    with patch.object(collector, "_fetch_lof_list_primary", side_effect=Exception("fail")):
        with patch.object(collector, "_fetch_lof_list_fallback", side_effect=Exception("fail")):
            try:
                collector.fetch_lof_fund_list()
            except Exception:
                pass

    status = collector._storage.get_data_source_status("lof_list")
    assert status is not None
    assert status["status"] == "failure"


def test_collector_primary_success_resets_failures():
    """主源成功时应重置失败计数"""
    collector = _create_collector()

    # 先制造一次失败
    with patch.object(collector, "_fetch_lof_list_primary", side_effect=Exception("fail")):
        with patch.object(collector, "_fetch_lof_list_fallback", return_value=[]):
            try:
                collector.fetch_lof_fund_list()
            except Exception:
                pass

    status = collector._storage.get_data_source_status("lof_list")
    assert status["consecutive_failures"] == 1

    # 主源成功，应重置失败计数
    with patch.object(collector, "_fetch_lof_list_primary", return_value=[
        {"code": "164906", "name": "测试", "status": "normal", "is_suspended": False, "daily_volume": 0.0},
    ]):
        result = collector.fetch_lof_fund_list()
        assert len(result) == 1

    status = collector._storage.get_data_source_status("lof_list")
    assert status["status"] == "ok"
    assert status["consecutive_failures"] == 0


def test_collector_switch_after_max_failures():
    """连续失败达到阈值后应直接走备用源"""
    collector = _create_collector(max_failures=2)

    # 第一次主源失败
    with patch.object(collector, "_fetch_lof_list_primary", side_effect=Exception("fail")):
        with patch.object(collector, "_fetch_lof_list_fallback", return_value=[]):
            try:
                collector.fetch_lof_fund_list()
            except Exception:
                pass

    # 第二次主源失败，达到阈值
    with patch.object(collector, "_fetch_lof_list_primary", side_effect=Exception("fail")):
        with patch.object(collector, "_fetch_lof_list_fallback", return_value=[
            {"code": "501050", "name": "备用", "status": "normal", "is_suspended": False, "daily_volume": 500.0},
        ]):
            result = collector.fetch_lof_fund_list()
            assert len(result) == 1
            assert result[0]["code"] == "501050"

    # 第三次，连续失败已超阈值，直接走备用源（不再调用主源）
    primary_called = {"value": False}

    def mock_primary_should_not_call(*args, **kwargs):
        primary_called["value"] = True
        raise Exception("不应被调用")

    with patch.object(collector, "_fetch_lof_list_primary", mock_primary_should_not_call):
        with patch.object(collector, "_fetch_lof_list_fallback", return_value=[
            {"code": "501050", "name": "备用", "status": "normal", "is_suspended": False, "daily_volume": 500.0},
        ]):
            result = collector.fetch_lof_fund_list()
            assert len(result) == 1
            # 主源不应被调用
            assert not primary_called["value"]


def test_collector_both_fail_raises():
    """主源和备用源都失败时应抛出RuntimeError"""
    collector = _create_collector()

    with patch.object(collector, "_fetch_lof_list_primary", side_effect=Exception("主源挂")):
        with patch.object(collector, "_fetch_lof_list_fallback", side_effect=Exception("备用也挂")):
            try:
                collector.fetch_lof_fund_list()
                assert False, "应该抛出异常"
            except RuntimeError as ex:
                assert "均失败" in str(ex)


def test_fetch_lof_iopv_returns_iopv_data():
    """fetch_lof_iopv应返回基金IOPV（净值）数据"""
    import pandas as pd
    from unittest.mock import patch

    collector = _create_collector()

    fake_df = pd.DataFrame({
        "收盘": [1.025, 1.030],
        "成交量": [5000, 6000],
    })

    with patch("akshare.fund_etf_hist_em", return_value=fake_df):
        result = collector.fetch_lof_iopv(["164906"])

    assert "164906" in result
    assert result["164906"]["iopv"] == 1.030
    assert result["164906"]["iopv_source"] == "estimated"


def test_fetch_lof_iopv_empty_codes():
    """空代码列表应返回空字典"""
    collector = _create_collector()
    result = collector.fetch_lof_iopv([])
    assert result == {}


def test_fetch_lof_iopv_failure_returns_zero():
    """获取失败时应返回iopv为0"""
    from unittest.mock import patch

    collector = _create_collector()

    with patch("akshare.fund_etf_hist_em", side_effect=Exception("网络错误")):
        result = collector.fetch_lof_iopv(["164906"])

    assert "164906" in result
    assert result["164906"]["iopv"] == 0.0


def test_fetch_bond_allocation_list_returns_data():
    """fetch_bond_allocation_list应返回即将发行转债及正股信息"""
    import pandas as pd
    from unittest.mock import patch

    collector = _create_collector()

    fake_bond_df = pd.DataFrame({
        "债券代码": ["113001", "127001"],
        "债券名称": ["测试转债1", "测试转债2"],
        "申购日期": ["2026-05-15", "2026-05-20"],
        "正股代码": ["600001", "000001"],
    })

    # akshare使用懒加载，需create=True创建属性
    with patch("akshare.bond_zh_cov_new_em", return_value=fake_bond_df, create=True):
        with patch("akshare.stock_individual_info_em", create=True) as mock_stock:
            mock_stock.side_effect = [
                pd.DataFrame({"item": ["股票简称", "最新价"], "value": ["测试股票1", "10.50"]}),
                pd.DataFrame({"item": ["股票简称", "最新价"], "value": ["测试股票2", "15.20"]}),
            ]
            result = collector.fetch_bond_allocation_list()

    assert len(result) == 2
    assert result[0]["code"] == "113001"
    assert result[0]["stock_code"] == "600001"
    assert result[0]["content_weight"] == 20.0


def test_fetch_bond_allocation_list_empty():
    """无发行数据时应返回空列表"""
    import pandas as pd
    from unittest.mock import patch

    collector = _create_collector()

    # akshare使用懒加载，需create=True创建属性
    with patch("akshare.bond_zh_cov_new_em", return_value=pd.DataFrame(), create=True):
        result = collector.fetch_bond_allocation_list()

    assert result == []
