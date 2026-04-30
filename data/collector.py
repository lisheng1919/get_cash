"""数据采集层，含主备源容灾切换"""

import logging
from typing import Dict, List, Optional

from data.storage import Storage

logger = logging.getLogger(__name__)


class DataCollector:
    """数据采集器，支持主备源自动切换

    主源失败时记录失败次数，连续失败达到阈值后切换到备用源。
    主源成功时重置失败计数。
    """

    def __init__(self, storage: Storage, ds_config: dict):
        """初始化数据采集器

        Args:
            storage: 存储实例，用于记录数据源状态
            ds_config: 数据源配置，支持以下键：
                - max_consecutive_failures: 连续失败切换阈值，默认3
                - market_primary: 行情主源名称，默认akshare
                - market_fallback: 行情备用源名称，默认sina
        """
        self._storage = storage
        self._max_failures = ds_config.get("max_consecutive_failures", 3)
        self._ds_config = ds_config

    # ==================== LOF基金列表 ====================

    def _fetch_lof_list_primary(self) -> List[Dict]:
        """主源获取LOF基金列表（akshare）

        使用akshare获取开放式基金列表，筛选代码以16或50开头的LOF基金。

        Returns:
            LOF基金列表，每项包含 code, name, status, is_suspended, daily_volume
        """
        try:
            import akshare as ak
            # akshare接口可能变化，用try包裹
            df = ak.fund_open_sina_info_em(symbol="基金")
            if df is None or df.empty:
                logger.warning("akshare返回空数据")
                return []

            result = []
            for _, row in df.iterrows():
                code = str(row.get("基金代码", "")).strip()
                # 筛选LOF基金：代码以16或50开头
                if not (code.startswith("16") or code.startswith("50")):
                    continue
                name = str(row.get("基金名称", "")).strip()
                result.append({
                    "code": code,
                    "name": name,
                    "status": "normal",
                    "is_suspended": False,
                    "daily_volume": 0.0,
                })
            return result
        except Exception as ex:
            logger.error("主源获取LOF基金列表失败: %s", ex)
            raise

    def _fetch_lof_list_fallback(self) -> List[Dict]:
        """备用源获取LOF基金列表（占位实现）

        后续可对接sina等其他数据源。

        Returns:
            LOF基金列表，当前返回空列表
        """
        logger.info("备用源获取LOF基金列表（尚未实现），返回空列表")
        return []

    def fetch_lof_fund_list(self) -> List[Dict]:
        """获取LOF基金列表，主源失败时自动切备用源

        主源成功时重置失败计数；主源失败时记录失败，
        连续失败达到max_failures时log切换提示并尝试备用源。

        Returns:
            LOF基金列表

        Raises:
            RuntimeError: 主源和备用源均失败时抛出
        """
        # 查询当前连续失败次数，决定是否直接走备用源
        source_status = self._storage.get_data_source_status("lof_list")
        consecutive = 0
        if source_status is not None:
            consecutive = source_status.get("consecutive_failures", 0)

        # 连续失败未达阈值，先尝试主源
        if consecutive < self._max_failures:
            try:
                result = self._fetch_lof_list_primary()
                # 主源成功，重置失败计数
                self._storage.update_data_source_status("lof_list", "ok")
                return result
            except Exception:
                # 主源失败，记录失败次数
                fail_count = self._storage.record_data_source_failure("lof_list")
                if fail_count >= self._max_failures:
                    logger.warning(
                        "LOF基金列表主源连续失败%d次，达到阈值，切换备用源",
                        fail_count,
                    )
        else:
            logger.warning(
                "LOF基金列表主源连续失败已达阈值(%d次)，直接使用备用源",
                consecutive,
            )

        # 尝试备用源
        try:
            result = self._fetch_lof_list_fallback()
            if result:
                logger.info("备用源获取LOF基金列表成功，共%d条", len(result))
            return result
        except Exception as ex:
            logger.error("备用源获取LOF基金列表也失败: %s", ex)
            raise RuntimeError("LOF基金列表主源和备用源均失败") from ex

    # ==================== LOF实时行情 ====================

    def fetch_lof_realtime(self, codes: List[str]) -> Dict[str, Dict]:
        """获取LOF实时行情

        Args:
            codes: LOF基金代码列表

        Returns:
            字典，key为基金代码，value为行情信息字典
        """
        if not codes:
            return {}

        result = {}
        try:
            import akshare as ak
            for code in codes:
                try:
                    df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
                    if df is not None and not df.empty:
                        latest = df.iloc[-1]
                        result[code] = {
                            "code": code,
                            "price": float(latest.get("收盘", 0)),
                            "volume": float(latest.get("成交量", 0)),
                        }
                except Exception as ex:
                    logger.warning("获取基金%s实时行情失败: %s", code, ex)
                    result[code] = {"code": code, "price": 0.0, "volume": 0.0}
        except ImportError:
            logger.error("akshare未安装，无法获取实时行情")
        return result

    # ==================== LOF基金IOPV（净值） ====================

    def fetch_lof_iopv(self, codes: List[str]) -> Dict[str, Dict]:
        """获取LOF基金IOPV（净值近似值）

        通过akshare获取基金最新净值作为IOPV的近似值。
        数据精度为日级别，非实时，标记为estimated。

        Args:
            codes: LOF基金代码列表

        Returns:
            字典，key为基金代码，value为 {"iopv": float, "iopv_source": "estimated"}
        """
        if not codes:
            return {}

        result = {}
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare未安装，无法获取IOPV数据")
            return {code: {"iopv": 0.0, "iopv_source": "estimated"} for code in codes}

        for code in codes:
            try:
                df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    iopv = float(latest.get("收盘", 0))
                else:
                    iopv = 0.0
            except Exception as ex:
                logger.warning("获取基金%s IOPV失败: %s", code, ex)
                iopv = 0.0
            result[code] = {"iopv": iopv, "iopv_source": "estimated"}
        return result

    # ==================== 可转债申购 ====================

    def fetch_bond_ipo_list(self) -> List[Dict]:
        """获取可转债申购列表

        Returns:
            可转债申购列表，每项包含 code, name, subscribe_date
        """
        try:
            import akshare as ak
            df = ak.bond_zh_cov_new_em()
            if df is None or df.empty:
                return []

            result = []
            for _, row in df.iterrows():
                code = str(row.get("债券代码", "")).strip()
                name = str(row.get("债券名称", "")).strip()
                subscribe_date = str(row.get("申购日期", "")).strip()
                result.append({
                    "code": code,
                    "name": name,
                    "subscribe_date": subscribe_date,
                })
            return result
        except Exception as ex:
            logger.error("获取可转债申购列表失败: %s", ex)
            return []

    # ==================== 可转债配债 ====================

    def fetch_bond_allocation_list(self) -> List[Dict]:
        """获取即将发行可转债及正股信息

        通过akshare获取可转债发行列表和正股基本信息。
        含权量（content_weight）akshare暂无此字段，使用默认估算值20%。

        Returns:
            配债列表，每项包含 code, name, subscribe_date,
            stock_code, stock_name, stock_price, content_weight
        """
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare未安装，无法获取配债数据")
            return []

        try:
            df = ak.bond_zh_cov_new_em()
        except Exception as ex:
            logger.error("获取可转债发行列表失败: %s", ex)
            return []

        if df is None or df.empty:
            return []

        result = []
        for _, row in df.iterrows():
            code = str(row.get("债券代码", "")).strip()
            name = str(row.get("债券名称", "")).strip()
            subscribe_date = str(row.get("申购日期", "")).strip()
            stock_code = str(row.get("正股代码", "")).strip()

            # 获取正股信息
            stock_name = ""
            stock_price = 0.0
            if stock_code:
                try:
                    stock_df = ak.stock_individual_info_em(symbol=stock_code)
                    if stock_df is not None and not stock_df.empty:
                        for _, srow in stock_df.iterrows():
                            item = str(srow.get("item", "")).strip()
                            value = srow.get("value", "")
                            if item == "股票简称":
                                stock_name = str(value).strip()
                            elif item == "最新价":
                                try:
                                    stock_price = float(value)
                                except (ValueError, TypeError):
                                    stock_price = 0.0
                except Exception as ex:
                    logger.warning("获取正股%s信息失败: %s", stock_code, ex)

            result.append({
                "code": code,
                "name": name,
                "subscribe_date": subscribe_date,
                "stock_code": stock_code,
                "stock_name": stock_name,
                "stock_price": stock_price,
                "content_weight": 20.0,
            })
        return result

    # ==================== 逆回购利率 ====================

    def fetch_reverse_repo_rate(self, code: str) -> Optional[float]:
        """获取逆回购利率

        Args:
            code: 逆回购代码，如131810（1天期深市）或204001（1天期沪市）

        Returns:
            当前利率，失败时返回None
        """
        try:
            import akshare as ak
            df = ak.bond_repurchase_quote_em(symbol=code)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                rate = float(latest.get("最新价", 0))
                return rate if rate > 0 else None
        except Exception as ex:
            logger.error("获取逆回购利率失败(code=%s): %s", code, ex)
        return None
