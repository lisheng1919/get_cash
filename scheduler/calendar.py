"""交易日历管理模块，提供交易日判断、节前交易日检测等功能"""

import logging
from datetime import date, timedelta
from typing import List, Tuple

logger = logging.getLogger(__name__)


class TradingCalendar:
    """交易日历类，管理节假日和交易日判断

    维护内存中的节假日集合，支持从SQLite存储加载日历数据。
    """

    def __init__(self):
        # 节假日集合
        self._holidays = set()  # type: set[date]
        # 节假日名称映射 date -> name
        self._holiday_names = {}  # type: dict[date, str]
        # 节前交易日映射 date -> name（长假前最后交易日）
        self._pre_holidays = {}  # type: dict[date, str]

    def add_holiday(self, d: date, name: str = "") -> None:
        """添加节假日

        Args:
            d: 节假日日期
            name: 节假日名称，可选
        """
        self._holidays.add(d)
        if name:
            self._holiday_names[d] = name

    def add_pre_holiday(self, d: date, name: str = "") -> None:
        """添加节前交易日（长假前最后一个交易日）

        Args:
            d: 节前交易日日期
            name: 名称描述，可选
        """
        self._pre_holidays[d] = name

    def is_trading_day(self, d: date) -> bool:
        """判断是否为交易日

        周末和节假日不是交易日，其余为交易日。

        Args:
            d: 待判断日期

        Returns:
            True表示交易日，False表示非交易日
        """
        # 周末不是交易日（weekday: 周一=0, 周日=6）
        if d.weekday() >= 5:
            return False
        # 节假日不是交易日
        if d in self._holidays:
            return False
        return True

    def is_pre_holiday(self, d: date) -> bool:
        """判断是否为节前交易日（长假前最后一个交易日）

        Args:
            d: 待判断日期

        Returns:
            True表示节前交易日
        """
        return d in self._pre_holidays

    def next_trading_day(self, d: date) -> date:
        """获取指定日期之后的下一个交易日

        从给定日期的下一天开始逐日查找，最多查找30天。

        Args:
            d: 起始日期

        Returns:
            下一个交易日

        Raises:
            ValueError: 30天内未找到交易日
        """
        candidate = d + timedelta(days=1)
        # 安全上限，防止无限循环
        for _ in range(30):
            if self.is_trading_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        raise ValueError("30天内未找到交易日")

    def get_upcoming_pre_holidays(self, from_date: date) -> List[Tuple[date, str]]:
        """获取从指定日期起即将到来的节前交易日

        按日期升序返回所有在 from_date 之后（含当天）的节前交易日。

        Args:
            from_date: 起始日期

        Returns:
            节前交易日列表，每个元素为 (日期, 名称) 元组
        """
        results = []
        for d, name in self._pre_holidays.items():
            if d >= from_date:
                results.append((d, name))
        # 按日期升序排列
        results.sort(key=lambda x: x[0])
        return results

    def load_from_storage(self, storage) -> None:
        """从SQLite存储加载日历数据

        读取 holiday_calendar 表中的所有记录，填充内存中的节假日和节前交易日集合。

        Args:
            storage: Storage 实例，需提供 is_trading_day/is_pre_holiday 等方法
        """
        cursor = storage._conn.execute(
            "SELECT date, is_trading_day, is_pre_holiday, holiday_name FROM holiday_calendar"
        )
        for row in cursor.fetchall():
            row_dict = dict(row) if not isinstance(row, dict) else row
            d = date.fromisoformat(row_dict["date"])
            # 非交易日且非周末，视为节假日
            is_trading = bool(row_dict["is_trading_day"])
            if not is_trading:
                self._holidays.add(d)
                holiday_name = row_dict.get("holiday_name", "")
                if holiday_name:
                    self._holiday_names[d] = holiday_name
            # 节前交易日
            is_pre = bool(row_dict["is_pre_holiday"])
            if is_pre:
                holiday_name = row_dict.get("holiday_name", "")
                self._pre_holidays[d] = holiday_name

    def _infer_holiday_name(self, month: int) -> str:
        """根据月份推断节假日名称

        Args:
            month: 月份（1-12）

        Returns:
            推断的节假日名称
        """
        month_name_map = {
            1: "元旦",
            2: "春节",
            4: "清明节",
            5: "劳动节",
            6: "端午节",
            9: "中秋节",
            10: "国庆节",
        }
        return month_name_map.get(month, "节假日")

    def sync_from_akshare(self, storage) -> None:
        """从akshare同步交易日历数据（增量更新）

        调用akshare获取历史交易日数据，推断非交易日和节前交易日，
        写入数据库并重新加载到内存。

        Args:
            storage: Storage 实例，用于数据库读写
        """
        # 延迟导入akshare，避免未安装时影响模块加载
        import akshare as ak

        # 拉取交易日数据
        df = ak.tool_trade_date_hist_sina()
        trade_date_strs = set(df["trade_date"].astype(str).tolist())
        trade_dates = set()
        for s in trade_date_strs:
            try:
                trade_dates.add(date.fromisoformat(s))
            except (ValueError, TypeError):
                logger.warning("跳过无效交易日: %s", s)

        if not trade_dates:
            logger.warning("akshare返回的交易日数据为空，跳过同步")
            return

        # 确定日期范围：从最早交易日到最晚交易日
        min_date = min(trade_dates)
        max_date = max(trade_dates)

        # 增量同步：检查数据库中已有数据的最大日期
        cursor = storage._conn.execute(
            "SELECT MAX(date) FROM holiday_calendar"
        )
        row = cursor.fetchone()
        last_synced = None
        if row and row[0]:
            last_synced = date.fromisoformat(row[0])
            # 如果已同步到最后，跳过
            if last_synced >= max_date:
                logger.info("交易日历已是最新，无需增量同步")
                self.load_from_storage(storage)
                return
            # 增量同步从已有数据的下一天开始
            min_date = last_synced + timedelta(days=1)

        logger.info(
            "开始同步交易日历: %s ~ %s",
            min_date.strftime("%Y-%m-%d"),
            max_date.strftime("%Y-%m-%d"),
        )

        # 推断非交易日：工作日但不在交易日集合中的日期
        non_trading_dates = set()
        current = min_date
        while current <= max_date:
            # 仅判断工作日（跳过周末）
            if current.weekday() < 5 and current not in trade_dates:
                non_trading_dates.add(current)
            current += timedelta(days=1)

        # 推断节前交易日：交易日后面到下一个交易日之间的日历天数>=3
        # （正常周末间隔为2天，超过2天即为长假，当前交易日为节前）
        pre_holiday_dates = {}
        for td in trade_dates:
            if td < min_date or td > max_date:
                continue
            # 查找下一个交易日
            next_day = td + timedelta(days=1)
            calendar_gap = 0
            check_day = next_day
            while check_day <= max_date:
                calendar_gap += 1
                if check_day in trade_dates:
                    break
                check_day += timedelta(days=1)
            # 日历间隔>=3天（超过正常周末2天），则当前交易日为节前
            if calendar_gap >= 3:
                # 查找最近的节假日名称（从后续非交易日中取月份）
                holiday_name = ""
                for gap_day in non_trading_dates:
                    if gap_day > td and gap_day < check_day:
                        holiday_name = self._infer_holiday_name(gap_day.month)
                        break
                pre_holiday_dates[td] = holiday_name

        # 写入数据库：交易日
        for td in trade_dates:
            if td < min_date or td > max_date:
                continue
            is_pre = td in pre_holiday_dates
            holiday_name = pre_holiday_dates.get(td, "")
            storage.upsert_holiday(
                td.strftime("%Y-%m-%d"),
                is_trading_day=True,
                is_pre_holiday=is_pre,
                holiday_name=holiday_name,
            )

        # 写入数据库：非交易日（节假日）
        for ntd in non_trading_dates:
            if ntd < min_date or ntd > max_date:
                continue
            holiday_name = self._infer_holiday_name(ntd.month)
            storage.upsert_holiday(
                ntd.strftime("%Y-%m-%d"),
                is_trading_day=False,
                is_pre_holiday=False,
                holiday_name=holiday_name,
            )

        # 重新加载到内存
        self.load_from_storage(storage)
        logger.info(
            "交易日历同步完成: 交易日=%d, 非交易日=%d, 节前=%d",
            len(trade_dates),
            len(non_trading_dates),
            len(pre_holiday_dates),
        )
