# -*- coding: utf-8 -*-
"""ConfigManager配置管理器测试"""

import sqlite3
import unittest
from data.models import init_db
from data.storage import Storage
from config_manager import (
    CONFIG_META,
    STRATEGY_ATTR_MAP,
    STRATEGY_SUB_OBJ_MAP,
    _value_to_str,
    _str_to_value,
    ConfigManager,
)


# ==================== 测试用FakeStrategy ====================

class FakePremiumCalculator:
    """模拟PremiumCalculator"""

    def __init__(self):
        self._normal_threshold = 3.0
        self._low_precision_threshold = 3.0


class FakeLofFilter:
    """模拟LofFilter"""

    def __init__(self):
        self._min_volume = 500


class FakeSignalGenerator:
    """模拟SignalGenerator"""

    def __init__(self):
        self._confirm_count = 3
        self._cooldown_minutes = 5


class FakeLofPremiumStrategy:
    """模拟LofPremiumStrategy，包含子对象"""

    name = "lof_premium"

    def __init__(self):
        self._enabled = True
        self._auto_trade = False
        self._auto_mute_enabled = True
        self._min_profit_yuan = 200
        self._auto_mute_paused_days = 30
        self._available_capital = 100000
        self._sell_commission_rate = 0.0003
        # 子对象
        self._calculator = FakePremiumCalculator()
        self._filter = FakeLofFilter()
        self._signal_generator = FakeSignalGenerator()


class FakeBondIpoStrategy:
    """模拟BondIpoStrategy"""

    name = "bond_ipo"

    def __init__(self):
        self._enabled = True
        self._auto_subscribe = True
        self._max_miss = 2


# ==================== 测试辅助函数 ====================

def _create_env():
    """创建测试环境：内存DB + Storage + ConfigManager + 示例config_dict"""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    storage = Storage(conn)
    # 构造与config.yaml结构一致的config_dict
    config_dict = {
        "strategies": {
            "bond_ipo": {"enabled": True},
            "bond_allocation": {"enabled": True},
            "reverse_repo": {"enabled": True},
            "lof_premium": {"enabled": True},
        },
        "bond_ipo": {
            "auto_subscribe": True,
            "notify_on_subscribe": True,
            "notify_on_winning": True,
            "notify_on_listing": True,
            "max_consecutive_miss": 2,
        },
        "bond_allocation": {
            "min_content_weight": 20,
            "min_safety_cushion": 5.0,
            "min_stock_volume": 1000,
            "max_stock_amount_ratio": 0.2,
            "notify_before_record_day": 1,
            "notify_on_listing": True,
            "conservative_factor": 0.8,
            "rush_warning_threshold": 5.0,
        },
        "reverse_repo": {
            "amount": 100000,
            "prefer_sh": True,
            "min_rate": 3.0,
            "reserve_ratio": 0.2,
            "remind_time": "14:30",
        },
        "lof_premium": {
            "poll_interval": 60,
            "random_delay_max": 3,
            "premium_threshold": 3.0,
            "low_precision_threshold": 3.0,
            "min_volume": 500,
            "confirm_count": 3,
            "cooldown_minutes": 5,
            "auto_trade": False,
            "auto_mute_enabled": True,
            "min_profit_yuan": 200,
            "auto_mute_paused_days": 30,
            "available_capital": 100000,
            "sell_commission_rate": 0.0003,
        },
        "notify": {
            "desktop": {"enabled": True},
            "wechat": {"enabled": False, "serverchan_key": ""},
            "dingtalk": {"enabled": False, "webhook": ""},
        },
        "risk": {
            "max_daily_trades_per_fund": 1,
            "max_single_trade_ratio": 0.3,
            "hard_stop_loss": 5.0,
            "bond_ipo_max_consecutive_miss": 2,
        },
        "system": {
            "startup_selfcheck": True,
            "heartbeat_interval": 300,
            "data_retention_days": 90,
            "data_aggregate_hours": True,
            "db_vacuum_weekly": True,
        },
    }
    manager = ConfigManager(storage, scheduler=None, config_dict=config_dict)
    return conn, storage, manager, config_dict


class TestConfigManager(unittest.TestCase):
    """ConfigManager配置管理器测试"""

    def test_init_from_yaml(self):
        """验证从config.yaml初始化配置到DB"""
        conn, storage, manager, _ = _create_env()
        try:
            manager.init_from_yaml()

            # 检查各分类的配置项数量
            strategy_items = storage.get_config_by_category("strategy")
            notify_items = storage.get_config_by_category("notify")
            risk_items = storage.get_config_by_category("risk")
            system_items = storage.get_config_by_category("system")

            # strategy分类应有bond_ipo + bond_allocation + reverse_repo + lof_premium的所有配置项
            self.assertGreater(len(strategy_items), 0)
            self.assertGreater(len(notify_items), 0)
            self.assertGreater(len(risk_items), 0)
            self.assertGreater(len(system_items), 0)

            # 验证具体配置值
            bond_ipo_enabled = storage.get_config_kv("strategy", "bond_ipo", "enabled")
            self.assertIsNotNone(bond_ipo_enabled)
            self.assertEqual(bond_ipo_enabled["value"], "1")

            # 验证非enabled配置来自独立段
            auto_sub = storage.get_config_kv("strategy", "bond_ipo", "auto_subscribe")
            self.assertIsNotNone(auto_sub)
            self.assertEqual(auto_sub["value"], "1")

            max_miss = storage.get_config_kv("strategy", "bond_ipo", "max_consecutive_miss")
            self.assertIsNotNone(max_miss)
            self.assertEqual(max_miss["value"], "2")

            # 验证通知配置
            desktop_enabled = storage.get_config_kv("notify", "desktop", "enabled")
            self.assertIsNotNone(desktop_enabled)
            self.assertEqual(desktop_enabled["value"], "1")

            # 验证风控配置
            max_trades = storage.get_config_kv("risk", "risk", "max_daily_trades_per_fund")
            self.assertIsNotNone(max_trades)
            self.assertEqual(max_trades["value"], "1")

            # 验证系统配置
            heartbeat = storage.get_config_kv("system", "system", "heartbeat_interval")
            self.assertIsNotNone(heartbeat)
            self.assertEqual(heartbeat["value"], "300")
        finally:
            conn.close()

    def test_init_from_yaml_idempotent(self):
        """验证第二次初始化不会覆盖已修改的值"""
        conn, storage, manager, _ = _create_env()
        try:
            # 第一次初始化
            manager.init_from_yaml()

            # 模拟用户修改了某个配置值
            storage.batch_update_config([{
                "category": "strategy",
                "section": "bond_ipo",
                "key": "max_consecutive_miss",
                "value": "5",
            }])

            # 第二次初始化（应跳过）
            manager.init_from_yaml()

            # 值应保持为5，不被覆盖回2
            item = storage.get_config_kv("strategy", "bond_ipo", "max_consecutive_miss")
            self.assertEqual(item["value"], "5")
        finally:
            conn.close()

    def test_get_config(self):
        """验证按分类查询配置"""
        conn, storage, manager, _ = _create_env()
        try:
            manager.init_from_yaml()

            # 按分类查询
            strategy_items = manager.get_config("strategy")
            self.assertGreater(len(strategy_items), 0)
            for item in strategy_items:
                self.assertEqual(item["category"], "strategy")

            # 查询所有分类
            all_items = manager.get_config()
            self.assertGreater(len(all_items), len(strategy_items))

            # 查询不存在的分类返回空列表
            empty_items = manager.get_config("nonexistent")
            self.assertEqual(len(empty_items), 0)
        finally:
            conn.close()

    def test_update_config_and_signal(self):
        """验证批量更新配置 + 重载信号"""
        conn, storage, manager, _ = _create_env()
        try:
            manager.init_from_yaml()

            # 确认无重载信号
            signals = storage.get_unprocessed_reload_signals()
            self.assertEqual(len(signals), 0)

            # 批量更新配置
            items = [
                {
                    "category": "strategy",
                    "section": "bond_ipo",
                    "key": "max_consecutive_miss",
                    "value": "5",
                },
                {
                    "category": "strategy",
                    "section": "lof_premium",
                    "key": "premium_threshold",
                    "value": "4.0",
                },
            ]
            manager.update_config(items)

            # 验证值已更新
            item1 = storage.get_config_kv("strategy", "bond_ipo", "max_consecutive_miss")
            self.assertEqual(item1["value"], "5")

            item2 = storage.get_config_kv("strategy", "lof_premium", "premium_threshold")
            self.assertEqual(item2["value"], "4.0")

            # 验证重载信号已插入
            signals = storage.get_unprocessed_reload_signals()
            self.assertEqual(len(signals), 1)
        finally:
            conn.close()

    def test_get_config_as_dict(self):
        """验证嵌套字典格式返回"""
        conn, storage, manager, _ = _create_env()
        try:
            manager.init_from_yaml()

            # 获取strategy分类的嵌套字典
            config_dict = manager.get_config_as_dict("strategy")

            # 验证结构
            self.assertIn("bond_ipo", config_dict)
            self.assertIn("bond_allocation", config_dict)
            self.assertIn("reverse_repo", config_dict)
            self.assertIn("lof_premium", config_dict)

            # 验证值类型转换
            bond_ipo = config_dict["bond_ipo"]
            self.assertIsInstance(bond_ipo["enabled"], bool)
            self.assertTrue(bond_ipo["enabled"])
            self.assertIsInstance(bond_ipo["auto_subscribe"], bool)
            self.assertIsInstance(bond_ipo["max_consecutive_miss"], int)
            self.assertEqual(bond_ipo["max_consecutive_miss"], 2)

            # 验证float类型
            lof = config_dict["lof_premium"]
            self.assertIsInstance(lof["premium_threshold"], float)
            self.assertAlmostEqual(lof["premium_threshold"], 3.0)
            self.assertIsInstance(lof["sell_commission_rate"], float)

            # 验证risk分类
            risk_dict = manager.get_config_as_dict("risk")
            self.assertIn("risk", risk_dict)
            self.assertIsInstance(risk_dict["risk"]["hard_stop_loss"], float)
        finally:
            conn.close()

    def test_reload_updates_strategy(self):
        """验证热加载将DB配置值写回策略实例属性"""
        conn, storage, manager, _ = _create_env()
        try:
            manager.init_from_yaml()

            # 注册模拟策略
            fake_lof = FakeLofPremiumStrategy()
            fake_bond_ipo = FakeBondIpoStrategy()
            manager.register_strategy("lof_premium", fake_lof)
            manager.register_strategy("bond_ipo", fake_bond_ipo)

            # 初始值验证
            self.assertTrue(fake_bond_ipo._enabled)
            self.assertEqual(fake_bond_ipo._max_miss, 2)
            self.assertTrue(fake_lof._enabled)
            self.assertEqual(fake_lof._calculator._normal_threshold, 3.0)
            self.assertEqual(fake_lof._filter._min_volume, 500)
            self.assertEqual(fake_lof._signal_generator._confirm_count, 3)

            # 修改DB中的值
            storage.batch_update_config([
                {"category": "strategy", "section": "bond_ipo", "key": "max_consecutive_miss", "value": "5"},
                {"category": "strategy", "section": "bond_ipo", "key": "enabled", "value": "0"},
                {"category": "strategy", "section": "lof_premium", "key": "premium_threshold", "value": "4.5"},
                {"category": "strategy", "section": "lof_premium", "key": "min_volume", "value": "800"},
                {"category": "strategy", "section": "lof_premium", "key": "confirm_count", "value": "5"},
                {"category": "strategy", "section": "lof_premium", "key": "available_capital", "value": "200000"},
                {"category": "strategy", "section": "lof_premium", "key": "sell_commission_rate", "value": "0.0005"},
            ])

            # 执行热加载
            manager.reload()

            # 验证策略属性已更新
            self.assertFalse(fake_bond_ipo._enabled)
            self.assertEqual(fake_bond_ipo._max_miss, 5)
            self.assertEqual(fake_lof._calculator._normal_threshold, 4.5)
            self.assertEqual(fake_lof._filter._min_volume, 800)
            self.assertEqual(fake_lof._signal_generator._confirm_count, 5)
            self.assertEqual(fake_lof._available_capital, 200000)
            self.assertAlmostEqual(fake_lof._sell_commission_rate, 0.0005)
        finally:
            conn.close()

    def test_check_reload_signals(self):
        """验证重载信号检查和处理"""
        conn, storage, manager, _ = _create_env()
        try:
            manager.init_from_yaml()

            # 注册模拟策略
            fake_bond_ipo = FakeBondIpoStrategy()
            manager.register_strategy("bond_ipo", fake_bond_ipo)

            # 修改DB并插入信号
            storage.batch_update_config([
                {"category": "strategy", "section": "bond_ipo", "key": "max_consecutive_miss", "value": "10"},
            ])
            storage.insert_reload_signal()

            # 执行信号检查
            manager.check_reload_signals()

            # 验证策略属性已更新
            self.assertEqual(fake_bond_ipo._max_miss, 10)

            # 验证信号已标记为已处理
            signals = storage.get_unprocessed_reload_signals()
            self.assertEqual(len(signals), 0)
        finally:
            conn.close()


class TestValueConversion(unittest.TestCase):
    """值转换辅助函数测试"""

    def test_value_to_str(self):
        """验证Python值转字符串"""
        self.assertEqual(_value_to_str(True, "bool"), "1")
        self.assertEqual(_value_to_str(False, "bool"), "0")
        self.assertEqual(_value_to_str(42, "int"), "42")
        self.assertEqual(_value_to_str(3.14, "float"), "3.14")
        self.assertEqual(_value_to_str("hello", "string"), "hello")

    def test_str_to_value(self):
        """验证字符串转Python值"""
        self.assertTrue(_str_to_value("1", "bool"))
        self.assertFalse(_str_to_value("0", "bool"))
        self.assertEqual(_str_to_value("42", "int"), 42)
        self.assertAlmostEqual(_str_to_value("3.14", "float"), 3.14)
        self.assertEqual(_str_to_value("hello", "string"), "hello")


class TestConfigMetaCompleteness(unittest.TestCase):
    """CONFIG_META完整性测试"""

    def test_strategy_attr_map_covers_all_strategies(self):
        """验证STRATEGY_ATTR_MAP覆盖CONFIG_META中的所有策略"""
        strategy_sections = CONFIG_META.get("strategy", {})
        for section in strategy_sections:
            self.assertIn(section, STRATEGY_ATTR_MAP,
                          f"STRATEGY_ATTR_MAP缺少策略: {section}")

    def test_strategy_attr_map_keys_in_config_meta(self):
        """验证STRATEGY_ATTR_MAP中的配置键都在CONFIG_META中定义"""
        for strategy_name, attr_map in STRATEGY_ATTR_MAP.items():
            meta_keys = set(CONFIG_META["strategy"][strategy_name].keys())
            for attr_name, config_key in attr_map.items():
                self.assertIn(config_key, meta_keys,
                              f"策略{strategy_name}的ATTR_MAP引用了不存在的配置键: {config_key}")

    def test_sub_obj_map_keys_in_config_meta(self):
        """验证STRATEGY_SUB_OBJ_MAP中的配置键都在CONFIG_META中定义"""
        for strategy_name, sub_map in STRATEGY_SUB_OBJ_MAP.items():
            meta_keys = set(CONFIG_META["strategy"][strategy_name].keys())
            for sub_obj, sub_attrs in sub_map.items():
                for sub_attr, (config_key, _value_type) in sub_attrs.items():
                    self.assertIn(config_key, meta_keys,
                                  f"策略{strategy_name}子对象{sub_obj}引用了不存在的配置键: {config_key}")


if __name__ == "__main__":
    unittest.main()
