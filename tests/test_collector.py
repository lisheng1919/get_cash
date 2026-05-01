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
    """连续失败达到阈值后仍会尝试主源（接口恢复后自动恢复），失败后走备用源"""
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

    # 第三次，即使超过阈值也会尝试主源；主源恢复后自动切回
    with patch.object(collector, "_fetch_lof_list_primary", return_value=[
        {"code": "164906", "name": "恢复", "status": "normal", "is_suspended": False, "daily_volume": 0.0},
    ]):
        result = collector.fetch_lof_fund_list()
        assert len(result) == 1
        assert result[0]["code"] == "164906"

    # 主源成功后失败计数应重置
    status = collector._storage.get_data_source_status("lof_list")
    assert status["status"] == "ok"
    assert status["consecutive_failures"] == 0


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

    # 批量估值接口返回空，触发回退到逐只查询
    fake_hist_df = pd.DataFrame({
        "收盘": [1.025, 1.030],
        "成交量": [5000, 6000],
    })

    with patch("akshare.fund_value_estimation_em", return_value=pd.DataFrame(), create=True):
        with patch("akshare.fund_etf_hist_em", return_value=fake_hist_df):
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
    import pandas as pd

    collector = _create_collector()

    with patch("akshare.fund_value_estimation_em", return_value=pd.DataFrame(), create=True):
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


def test_fetch_lof_purchase_status():
    """fetch_lof_purchase_status应返回LOF基金的申购状态、限额和费率"""
    import pandas as pd
    from unittest.mock import patch

    collector = _create_collector()

    # 构造fund_purchase_em()的返回数据（使用实际API的列名）
    fake_df = pd.DataFrame({
        "基金代码": ["164906", "501050", "162719", "510001"],
        "基金简称": ["某某LOF-A", "某某LOF-B", "某某LOF-C", "某某股票基金"],
        "基金类型": ["指数型-股票", "指数型-股票", "指数型-海外股票", "股票型"],
        "申购状态": ["开放申购", "限大额", "暂停申购", "开放申购"],
        "赎回状态": ["开放赎回", "开放赎回", "开放赎回", "开放赎回"],
        "日累计限定金额": [0, 20000, 0, 0],
        "手续费": [0.15, 0.12, 0.15, 1.50],
    })

    with patch("akshare.fund_purchase_em", return_value=fake_df, create=True):
        result = collector.fetch_lof_purchase_status()

    # 只应返回基金简称含LOF的基金，key带市场前缀
    assert "sz164906" in result
    assert "sh501050" in result
    assert "sz162719" in result
    assert "510001" not in result  # 简称不含LOF
    assert "sh510001" not in result

    # 验证数据格式
    assert result["sz164906"]["purchase_status"] == "开放申购"
    assert result["sz164906"]["purchase_limit"] == 0
    assert result["sz164906"]["purchase_fee_rate"] == 0.0015

    assert result["sh501050"]["purchase_status"] == "限大额"
    assert result["sh501050"]["purchase_limit"] == 20000

    assert result["sz162719"]["purchase_status"] == "暂停申购"
    assert result["sz162719"]["purchase_limit"] == 0


def test_fetch_lof_fund_list_primary_uses_eastmoney():
    """验证主源使用fund_value_estimation_em获取LOF列表"""
    import pandas as pd

    mock_df = pd.DataFrame({
        "基金代码": ["164906", "501050"],
        "基金简称": ["交银互联网", "华夏上证50"],
        "估算值": [1.0, 2.0],
    })

    called = {"estimation": False, "sina": False}

    original_estimation = __import__("akshare").fund_value_estimation_em
    original_sina = __import__("akshare").fund_etf_category_sina

    def fake_estimation(symbol):
        called["estimation"] = True
        assert symbol == "LOF"
        return mock_df

    def fake_sina(symbol):
        called["sina"] = True
        return pd.DataFrame()

    collector = _create_collector()

    with patch("akshare.fund_value_estimation_em", fake_estimation, create=True):
        with patch("akshare.fund_etf_category_sina", fake_sina, create=True):
            result = collector._fetch_lof_list_primary()

    assert called["estimation"] is True, "主源应调用fund_value_estimation_em"
    assert called["sina"] is False, "主源不应调用fund_etf_category_sina"
    assert len(result) >= 1, "应返回基金列表"


def test_fetch_lof_fund_list_fallback_uses_sina():
    """验证备源使用fund_etf_category_sina获取LOF列表"""
    import pandas as pd

    mock_df = pd.DataFrame({
        "代码": ["164906"],
        "名称": ["交银互联网"],
        "最新价": [1.5],
        "成交额": [50000],
    })

    called = {"sina": False}

    def fake_sina(symbol):
        called["sina"] = True
        assert symbol == "LOF基金"
        return mock_df

    collector = _create_collector()

    with patch("akshare.fund_etf_category_sina", fake_sina, create=True):
        result = collector._fetch_lof_list_fallback()

    assert called["sina"] is True, "备源应调用fund_etf_category_sina"
    assert len(result) == 1
    assert result[0]["code"] == "164906"


def test_fetch_lof_iopv_uses_primary_cache():
    """验证fetch_lof_iopv优先使用主源缓存的IOPV"""
    import pandas as pd

    collector = _create_collector()
    # 模拟主源已缓存IOPV
    collector._lof_iopv_cache = {"164906": 1.025, "501050": 2.030}

    with patch("akshare.fund_value_estimation_em", return_value=pd.DataFrame(), create=True):
        result = collector.fetch_lof_iopv(["164906", "501050"])

    assert result["164906"]["iopv"] == 1.025
    assert result["501050"]["iopv"] == 2.030
