"""交易日历管理模块，提供交易日判断、节前交易日检测等功能"""

from datetime import date, timedelta
from typing import List, Tuple


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
