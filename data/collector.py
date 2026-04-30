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

        使用akshare的fund_etf_category_sina接口直接获取LOF基金列表及行情。
        同时缓存价格数据供fetch_lof_realtime和fetch_lof_iopv使用。

        Returns:
            LOF基金列表，每项包含 code, name, status, is_suspended, daily_volume
        """
        try:
            import akshare as ak
            df = ak.fund_etf_category_sina(symbol="LOF基金")
            if df is None or df.empty:
                logger.warning("akshare返回空数据")
                return []

            result = []
            # 缓存行情数据，避免后续重复请求
            self._lof_price_cache = {}
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                if not code:
                    continue
                name = str(row.get("名称", "")).strip()
                # 成交额（元）转万元
                amount = float(row.get("成交额", 0) or 0)
                daily_volume = amount / 10000.0
                # 最新价为0视为停牌
                price = float(row.get("最新价", 0) or 0)
                is_suspended = price <= 0
                # 缓存价格
                if price > 0:
                    self._lof_price_cache[code] = price
                result.append({
                    "code": code,
                    "name": name,
                    "status": "normal",
                    "is_suspended": is_suspended,
                    "daily_volume": round(daily_volume, 2),
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
        # 始终先尝试主源（即使之前达到阈值也尝试一次，以便接口恢复后自动恢复）
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

        优先使用列表获取阶段缓存的价格，缓存未命中时回退到逐只查询。

        Args:
            codes: LOF基金代码列表

        Returns:
            字典，key为基金代码，value为行情信息字典
        """
        if not codes:
            return {}

        result = {}
        # 优先使用缓存（来自fund_etf_category_sina的实时数据）
        cache = getattr(self, "_lof_price_cache", {})
        missed_codes = []
        for code in codes:
            if code in cache:
                result[code] = {"code": code, "price": cache[code], "volume": 0.0}
            else:
                missed_codes.append(code)

        # 缓存未命中时回退到逐只查询
        if missed_codes:
            try:
                import akshare as ak
                for code in missed_codes:
                    try:
                        df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
                        if df is not None and not df.empty:
                            latest = df.iloc[-1]
                            result[code] = {
                                "code": code,
                                "price": float(latest.get("收盘", 0)),
                                "volume": float(latest.get("成交量", 0)),
                            }
                        else:
                            result[code] = {"code": code, "price": 0.0, "volume": 0.0}
                    except Exception as ex:
                        logger.warning("获取基金%s实时行情失败: %s", code, ex)
                        result[code] = {"code": code, "price": 0.0, "volume": 0.0}
            except ImportError:
                logger.error("akshare未安装，无法获取实时行情")
                for code in missed_codes:
                    result[code] = {"code": code, "price": 0.0, "volume": 0.0}
        return result

    # ==================== LOF基金IOPV（净值） ====================

    @staticmethod
    def _strip_code_prefix(code: str) -> str:
        """去掉基金代码的sz/sh前缀

        Args:
            code: 可能带前缀的基金代码，如 sz164906

        Returns:
            纯数字代码，如 164906
        """
        return code[2:] if len(code) > 2 and code[:2] in ("sz", "sh") else code

    def fetch_lof_iopv(self, codes: List[str]) -> Dict[str, Dict]:
        """获取LOF基金IOPV（净值近似值）

        优先使用fund_value_estimation_em批量获取LOF估值，失败时回退逐只查询。
        批量接口一次请求覆盖所有LOF基金，大幅减少网络请求数。

        Args:
            codes: LOF基金代码列表（可能含sz/sh前缀）

        Returns:
            字典，key为基金代码，value为 {"iopv": float, "iopv_source": "estimated"}
        """
        if not codes:
            return {}

        result = {}
        # 尝试批量获取LOF估值数据（一次请求覆盖所有LOF）
        try:
            import akshare as ak
            try:
                est_df = ak.fund_value_estimation_em(symbol="LOF")
                if est_df is not None and not est_df.empty:
                    # akshare返回的估值列名含动态日期前缀，如 "2026-04-30-估值数据-估算值"
                    # 需要按模式匹配找到估算值列
                    est_col = None
                    for col in est_df.columns:
                        if "估算值" in str(col) and "单位净值" not in str(col):
                            est_col = col
                            break
                    if est_col is None:
                        logger.warning("未找到估值列，可用列: %s", list(est_df.columns))

                    # 构建估值映射（纯数字代码 -> 估值）
                    est_map = {}
                    if est_col is not None:
                        for _, row in est_df.iterrows():
                            est_code = str(row.get("基金代码", "")).strip()
                            est_value = row.get(est_col, 0)
                            if est_code and est_value and str(est_value).strip() not in ("", "---", "--"):
                                try:
                                    est_map[est_code] = float(est_value)
                                except (ValueError, TypeError):
                                    pass

                    # 匹配时去掉sz/sh前缀
                    for code in codes:
                        pure_code = self._strip_code_prefix(code)
                        if pure_code in est_map:
                            result[code] = {"iopv": est_map[pure_code], "iopv_source": "estimated"}
            except Exception as ex:
                logger.warning("批量获取LOF估值失败，回退逐只查询: %s", ex)
        except ImportError:
            logger.error("akshare未安装，无法获取IOPV数据")
            return {code: {"iopv": 0.0, "iopv_source": "estimated"} for code in codes}

        # 对未获取到估值的基金逐只查询历史净值
        missed_codes = [c for c in codes if c not in result]
        if missed_codes:
            logger.debug("批量估值未覆盖%d只基金，逐只查询", len(missed_codes))
            try:
                import akshare as ak
                for code in missed_codes:
                    pure_code = self._strip_code_prefix(code)
                    try:
                        df = ak.fund_etf_hist_em(symbol=pure_code, period="daily", adjust="qfq")
                        if df is not None and not df.empty:
                            latest = df.iloc[-1]
                            iopv = float(latest.get("收盘", 0))
                        else:
                            iopv = 0.0
                    except Exception as ex:
                        logger.debug("获取基金%s IOPV失败: %s", code, ex)
                        iopv = 0.0
                    result[code] = {"iopv": iopv, "iopv_source": "estimated"}
            except ImportError:
                for code in missed_codes:
                    result[code] = {"iopv": 0.0, "iopv_source": "estimated"}

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
