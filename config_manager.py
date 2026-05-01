# -*- coding: utf-8 -*-
"""配置管理器，负责配置项的初始化、读取、热加载和信号机制"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ==================== 配置元数据 ====================
# 定义所有配置项的标签、描述、类型和默认值
# 结构: {category: {section: {key: {label, description, value_type, default}}}}

CONFIG_META = {
    "strategy": {
        "bond_ipo": {
            "enabled": {
                "label": "启用策略",
                "description": "是否启用可转债打新策略",
                "value_type": "bool",
                "default": True,
            },
            "auto_subscribe": {
                "label": "自动申购",
                "description": "是否自动申购可转债",
                "value_type": "bool",
                "default": True,
            },
            "notify_on_subscribe": {
                "label": "申购通知",
                "description": "申购日是否推送通知",
                "value_type": "bool",
                "default": True,
            },
            "notify_on_winning": {
                "label": "中签通知",
                "description": "中签后是否推送通知",
                "value_type": "bool",
                "default": True,
            },
            "notify_on_listing": {
                "label": "上市通知",
                "description": "上市日是否推送通知",
                "value_type": "bool",
                "default": True,
            },
            "max_consecutive_miss": {
                "label": "连续未中签暂停阈值",
                "description": "连续未中签达到此次数后暂停申购",
                "value_type": "int",
                "default": 2,
            },
        },
        "bond_allocation": {
            "enabled": {
                "label": "启用策略",
                "description": "是否启用可转债配债策略",
                "value_type": "bool",
                "default": True,
            },
            "min_content_weight": {
                "label": "最低含权量(%)",
                "description": "百股含权量低于此百分比的标的被过滤",
                "value_type": "int",
                "default": 20,
            },
            "min_safety_cushion": {
                "label": "最低安全垫(%)",
                "description": "安全垫低于此百分比的标的被过滤",
                "value_type": "float",
                "default": 5.0,
            },
            "min_stock_volume": {
                "label": "最低正股成交量",
                "description": "正股最低成交量(手)要求",
                "value_type": "int",
                "default": 1000,
            },
            "max_stock_amount_ratio": {
                "label": "最大正股金额占比",
                "description": "单只正股投入不超过总资金的比例",
                "value_type": "float",
                "default": 0.2,
            },
            "notify_before_record_day": {
                "label": "登记日前通知天数",
                "description": "在股权登记日前多少天推送通知",
                "value_type": "int",
                "default": 1,
            },
            "notify_on_listing": {
                "label": "上市通知",
                "description": "转债上市日是否推送通知",
                "value_type": "bool",
                "default": True,
            },
            "conservative_factor": {
                "label": "保守系数",
                "description": "历史平均溢价率的保守折减系数",
                "value_type": "float",
                "default": 0.8,
            },
            "rush_warning_threshold": {
                "label": "抢权预警阈值(%)",
                "description": "正股近期涨幅超过此阈值触发抢权预警",
                "value_type": "float",
                "default": 5.0,
            },
        },
        "reverse_repo": {
            "enabled": {
                "label": "启用策略",
                "description": "是否启用逆回购策略",
                "value_type": "bool",
                "default": True,
            },
            "amount": {
                "label": "总资金量(元)",
                "description": "参与逆回购的总资金量",
                "value_type": "int",
                "default": 100000,
            },
            "prefer_sh": {
                "label": "优先沪市",
                "description": "资金充足时优先选择沪市逆回购品种",
                "value_type": "bool",
                "default": True,
            },
            "min_rate": {
                "label": "最低利率(%)",
                "description": "低于此年化利率不做逆回购",
                "value_type": "float",
                "default": 3.0,
            },
            "reserve_ratio": {
                "label": "资金保留比例",
                "description": "做逆回购时保留的资金比例",
                "value_type": "float",
                "default": 0.2,
            },
            "remind_time": {
                "label": "提醒时间",
                "description": "每日推送逆回购提醒的时间(HH:MM)",
                "value_type": "string",
                "default": "14:30",
            },
        },
        "lof_premium": {
            "enabled": {
                "label": "启用策略",
                "description": "是否启用LOF溢价套利策略",
                "value_type": "bool",
                "default": True,
            },
            "poll_interval": {
                "label": "轮询间隔(秒)",
                "description": "LOF溢价率轮询间隔秒数",
                "value_type": "int",
                "default": 60,
            },
            "random_delay_max": {
                "label": "随机延迟上限(秒)",
                "description": "每次轮询增加的随机延迟上限，避免固定频率",
                "value_type": "int",
                "default": 3,
            },
            "premium_threshold": {
                "label": "溢价率阈值(%)",
                "description": "实时IOPV时的溢价率阈值",
                "value_type": "float",
                "default": 3.0,
            },
            "low_precision_threshold": {
                "label": "低精度溢价阈值(%)",
                "description": "非实时IOPV(估算值)时的溢价率阈值",
                "value_type": "float",
                "default": 3.0,
            },
            "min_volume": {
                "label": "最低日成交量(万元)",
                "description": "日成交量低于此值的基金被过滤",
                "value_type": "int",
                "default": 500,
            },
            "confirm_count": {
                "label": "连续确认次数",
                "description": "溢价率连续达到阈值的次数后才触发信号",
                "value_type": "int",
                "default": 3,
            },
            "cooldown_minutes": {
                "label": "冷却期(分钟)",
                "description": "同一基金两次信号的最小间隔分钟数",
                "value_type": "int",
                "default": 5,
            },
            "auto_trade": {
                "label": "自动交易",
                "description": "是否启用自动交易（需TradeExecutor接入）",
                "value_type": "bool",
                "default": False,
            },
            "auto_mute_enabled": {
                "label": "自动静默",
                "description": "是否在利润不足时自动静默基金",
                "value_type": "bool",
                "default": True,
            },
            "min_profit_yuan": {
                "label": "最低利润(元)",
                "description": "套利净利润低于此金额时触发自动静默",
                "value_type": "int",
                "default": 200,
            },
            "auto_mute_paused_days": {
                "label": "自动静默天数",
                "description": "自动静默后暂停监控的天数",
                "value_type": "int",
                "default": 30,
            },
            "available_capital": {
                "label": "可用资金(元)",
                "description": "LOF套利可用资金总额",
                "value_type": "int",
                "default": 100000,
            },
            "sell_commission_rate": {
                "label": "卖出佣金率",
                "description": "卖出佣金率(小数，如0.0003表示万三)",
                "value_type": "float",
                "default": 0.0003,
            },
        },
    },
    "notify": {
        "desktop": {
            "enabled": {
                "label": "启用桌面通知",
                "description": "是否启用桌面弹窗通知",
                "value_type": "bool",
                "default": True,
            },
        },
        "wechat": {
            "enabled": {
                "label": "启用微信通知",
                "description": "是否启用Server酱微信推送",
                "value_type": "bool",
                "default": False,
            },
            "serverchan_key": {
                "label": "Server酱Key",
                "description": "Server酱推送密钥",
                "value_type": "string",
                "default": "",
            },
        },
        "dingtalk": {
            "enabled": {
                "label": "启用钉钉通知",
                "description": "是否启用钉钉Webhook推送",
                "value_type": "bool",
                "default": False,
            },
            "webhook": {
                "label": "钉钉Webhook",
                "description": "钉钉机器人Webhook地址",
                "value_type": "string",
                "default": "",
            },
        },
    },
    "risk": {
        "risk": {
            "max_daily_trades_per_fund": {
                "label": "单基金每日最大交易次数",
                "description": "同一基金每日最大交易次数限制",
                "value_type": "int",
                "default": 1,
            },
            "max_single_trade_ratio": {
                "label": "单笔交易最大占比",
                "description": "单笔交易金额占总资金的最大比例",
                "value_type": "float",
                "default": 0.3,
            },
            "hard_stop_loss": {
                "label": "硬止损(%)",
                "description": "单笔交易最大允许亏损百分比",
                "value_type": "float",
                "default": 5.0,
            },
            "bond_ipo_max_consecutive_miss": {
                "label": "打新连续未中签上限",
                "description": "可转债打新连续未中签最大次数（风控全局限制）",
                "value_type": "int",
                "default": 2,
            },
        },
    },
    "system": {
        "system": {
            "startup_selfcheck": {
                "label": "启动自检",
                "description": "系统启动时是否执行自检",
                "value_type": "bool",
                "default": True,
            },
            "heartbeat_interval": {
                "label": "心跳间隔(秒)",
                "description": "系统心跳检测间隔秒数",
                "value_type": "int",
                "default": 300,
            },
            "data_retention_days": {
                "label": "数据保留天数",
                "description": "历史数据保留天数，超过则自动清理",
                "value_type": "int",
                "default": 90,
            },
            "data_aggregate_hours": {
                "label": "数据聚合",
                "description": "是否启用小时级数据聚合",
                "value_type": "bool",
                "default": True,
            },
            "db_vacuum_weekly": {
                "label": "每周数据库清理",
                "description": "是否每周自动执行SQLite VACUUM",
                "value_type": "bool",
                "default": True,
            },
        },
    },
}

# ==================== 策略属性映射 ====================
# 策略内部属性名 → 配置键名的映射
# 用于热加载时将DB值写回策略实例的属性

STRATEGY_ATTR_MAP = {
    "bond_ipo": {
        "_enabled": "enabled",
        "_auto_subscribe": "auto_subscribe",
        "_max_miss": "max_consecutive_miss",
    },
    "bond_allocation": {
        "_enabled": "enabled",
        "_min_content_weight": "min_content_weight",
        "_min_safety_cushion": "min_safety_cushion",
        "_conservative_factor": "conservative_factor",
        "_rush_threshold": "rush_warning_threshold",
    },
    "reverse_repo": {
        "_enabled": "enabled",
        "_min_rate": "min_rate",
        "_reserve_ratio": "reserve_ratio",
        "_amount": "amount",
        "_prefer_sh": "prefer_sh",
    },
    "lof_premium": {
        "_enabled": "enabled",
        "_auto_trade": "auto_trade",
        "_auto_mute_enabled": "auto_mute_enabled",
        "_min_profit_yuan": "min_profit_yuan",
        "_auto_mute_paused_days": "auto_mute_paused_days",
        "_available_capital": "available_capital",
        "_sell_commission_rate": "sell_commission_rate",
    },
}

# ==================== 策略子对象属性映射 ====================
# 用于LOF溢价策略中calculator/filter/signal_generator子对象的属性映射
# 格式: {策略名: {子对象属性名: {子对象内部属性名: (配置键名, 值类型)}}}

STRATEGY_SUB_OBJ_MAP = {
    "lof_premium": {
        "_calculator": {
            "_normal_threshold": ("premium_threshold", float),
            "_low_precision_threshold": ("low_precision_threshold", float),
        },
        "_filter": {
            "_min_volume": ("min_volume", int),
        },
        "_signal_generator": {
            "_confirm_count": ("confirm_count", int),
            "_cooldown_minutes": ("cooldown_minutes", int),
        },
    },
}


def _value_to_str(value: Any, value_type: str) -> str:
    """将Python值转换为字符串存储

    Args:
        value: Python值
        value_type: 值类型(bool/int/float/string)

    Returns:
        字符串表示
    """
    if value_type == "bool":
        return "1" if value else "0"
    return str(value)


def _str_to_value(value_str: str, value_type: str) -> Any:
    """将字符串还原为Python值

    Args:
        value_str: 数据库中的字符串值
        value_type: 值类型(bool/int/float/string)

    Returns:
        转换后的Python值
    """
    if value_type == "bool":
        return value_str == "1"
    if value_type == "int":
        return int(value_str)
    if value_type == "float":
        return float(value_str)
    # string类型直接返回
    return value_str


class ConfigManager:
    """配置管理器

    负责：
    1. 从config.yaml初始化配置到DB（仅DB为空时执行）
    2. 提供配置的查询和修改接口
    3. 通过信号机制实现跨进程配置热加载
    4. 将DB配置值回写到策略实例属性
    """

    def __init__(self, storage, scheduler, config_dict: dict):
        """初始化配置管理器

        Args:
            storage: Storage实例，用于读写配置KV
            scheduler: 调度器实例，预留用于任务管理
            config_dict: 从config.yaml加载的原始配置字典
        """
        self._storage = storage
        self._scheduler = scheduler
        self._config_dict = config_dict
        # 已注册的策略实例 {策略名: 策略实例}
        self._strategies: Dict[str, Any] = {}

    def register_strategy(self, name: str, strategy) -> None:
        """注册策略实例

        Args:
            name: 策略名称，如"bond_ipo"
            strategy: 策略实例
        """
        self._strategies[name] = strategy
        logger.info("已注册策略: %s", name)

    def init_from_yaml(self) -> None:
        """从config.yaml初始化配置到DB

        仅当DB中config_kv表对应分类为空时执行写入，避免覆盖用户修改。
        逐分类检查：只跳过已有数据的分类，其他分类正常初始化。
        """
        # 收集已有数据的分类
        populated_categories = set()
        for category in CONFIG_META:
            existing = self._storage.get_config_by_category(category)
            if existing:
                populated_categories.add(category)
                logger.info("DB已有配置(category=%s, %d条)，跳过该分类", category, len(existing))

        # 遍历CONFIG_META写入，跳过已有数据的分类
        count = 0
        for category, sections in CONFIG_META.items():
            if category in populated_categories:
                continue
            for section, keys in sections.items():
                for key, meta in keys.items():
                    value = self._get_yaml_value(
                        category, section, key, meta["default"]
                    )
                    value_str = _value_to_str(value, meta["value_type"])
                    self._storage.upsert_config_kv(
                        category=category,
                        section=section,
                        key=key,
                        value=value_str,
                        value_type=meta["value_type"],
                        label=meta["label"],
                        description=meta["description"],
                    )
                    count += 1

        if count > 0:
            logger.info("从config.yaml初始化配置完成，共写入%d条", count)
        else:
            logger.info("所有分类已有配置，跳过初始化")

    def _get_yaml_value(self, category: str, section: str, key: str, default: Any) -> Any:
        """从config_dict中提取配置值

        strategy类别的配置在config_dict["strategies"][section]和config_dict[section]中
        其他类别直接在config_dict[category][section]中

        Args:
            category: 分类名(strategy/notify/risk/system)
            section: 段名(如bond_ipo, desktop)
            key: 配置键名
            default: 默认值

        Returns:
            配置值
        """
        try:
            if category == "strategy":
                # 策略配置分两处：enabled在strategies段，其他在独立段
                if key == "enabled":
                    return self._config_dict.get("strategies", {}).get(section, {}).get(key, default)
                return self._config_dict.get(section, {}).get(key, default)
            # 其他类别：notify/risk/system
            return self._config_dict.get(category, {}).get(section, {}).get(key, default)
        except (KeyError, TypeError, AttributeError):
            return default

    def get_config(self, category: Optional[str] = None) -> List[Dict]:
        """查询配置项

        Args:
            category: 分类名，为None时返回所有配置

        Returns:
            配置项列表，每项为包含所有字段的字典
        """
        if category is not None:
            return self._storage.get_config_by_category(category)

        # 返回所有配置
        result = []
        for cat in CONFIG_META:
            result.extend(self._storage.get_config_by_category(cat))
        return result

    def get_config_as_dict(self, category: str) -> Dict:
        """按分类返回嵌套字典格式的配置

        返回格式: {section: {key: python_value}}

        Args:
            category: 分类名

        Returns:
            嵌套字典
        """
        items = self._storage.get_config_by_category(category)
        result: Dict[str, Dict[str, Any]] = {}
        for item in items:
            section = item["section"]
            key = item["key"]
            value = _str_to_value(item["value"], item["value_type"])
            if section not in result:
                result[section] = {}
            result[section][key] = value
        return result

    def update_config(self, items: List[Dict]) -> None:
        """批量更新配置并插入重载信号

        每个item需包含: category, section, key, value(字符串形式)

        Args:
            items: 待更新的配置项列表
        """
        if not items:
            return
        self._storage.batch_update_config(items)
        # 插入重载信号，通知其他进程/线程刷新配置
        self._storage.insert_reload_signal()
        logger.info("批量更新配置%d条，已插入重载信号", len(items))

    def reload(self) -> None:
        """从DB重新加载配置到已注册的策略实例

        遍历STRATEGY_ATTR_MAP和STRATEGY_SUB_OBJ_MAP，
        将DB中的配置值通过setattr写回策略实例属性。
        """
        # 读取所有strategy类别的配置
        strategy_config = self.get_config_as_dict("strategy")

        for strategy_name, strategy in self._strategies.items():
            # 处理策略直接属性
            attr_map = STRATEGY_ATTR_MAP.get(strategy_name, {})
            for attr_name, config_key in attr_map.items():
                section_config = strategy_config.get(strategy_name, {})
                if config_key in section_config:
                    setattr(strategy, attr_name, section_config[config_key])

            # 处理策略子对象属性
            sub_obj_map = STRATEGY_SUB_OBJ_MAP.get(strategy_name, {})
            for sub_obj_attr, sub_attrs in sub_obj_map.items():
                sub_obj = getattr(strategy, sub_obj_attr, None)
                if sub_obj is None:
                    continue
                for sub_attr_name, (config_key, _value_type) in sub_attrs.items():
                    section_config = strategy_config.get(strategy_name, {})
                    if config_key in section_config:
                        setattr(sub_obj, sub_attr_name, section_config[config_key])

        logger.info("配置热加载完成，已更新%d个策略实例", len(self._strategies))

    def check_reload_signals(self) -> None:
        """检查未处理的重载信号，有则执行reload并标记已处理"""
        signals = self._storage.get_unprocessed_reload_signals()
        if not signals:
            return

        # 有未处理信号，执行热加载
        self.reload()

        # 标记所有信号为已处理
        for signal in signals:
            self._storage.mark_reload_signal_processed(signal["id"])

        logger.info("处理了%d条配置重载信号", len(signals))
