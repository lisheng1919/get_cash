import logging
import sqlite3
import sys
from pathlib import Path

from config_loader import load_config, validate_config
from data.models import init_db
from data.storage import Storage
from data.collector import DataCollector
from scheduler.calendar import TradingCalendar
from scheduler.scheduler import StrategyScheduler
from strategies.bond_ipo import BondIpoStrategy
from strategies.reverse_repo import ReverseRepoStrategy
from strategies.bond_allocation import BondAllocationStrategy
from notify.base import NotificationManager
from notify.desktop import DesktopNotifier
from notify.wechat import WechatNotifier
from notify.dingtalk import DingtalkNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def setup_database(db_path: str) -> sqlite3.Connection:
    """初始化数据库连接并建表

    Args:
        db_path: 数据库文件路径

    Returns:
        已初始化的数据库连接
    """
    conn = sqlite3.connect(db_path)
    init_db(conn)
    return conn


def setup_notifier(config: dict) -> NotificationManager:
    """根据配置初始化通知管理器，注册已启用的通知渠道

    Args:
        config: 完整配置字典

    Returns:
        已注册通知渠道的通知管理器
    """
    notify_config = config.get("notify", {})
    dual_events = notify_config.get("dual_channel_events", [])
    mgr = NotificationManager(notify_config, dual_channel_events=dual_events)

    # 桌面通知
    if notify_config.get("desktop", {}).get("enabled", False):
        mgr.register("desktop", DesktopNotifier())

    # 微信通知（Server酱）
    wechat_key = notify_config.get("wechat", {}).get("serverchan_key", "")
    if notify_config.get("wechat", {}).get("enabled", False) and wechat_key:
        mgr.register("wechat", WechatNotifier(wechat_key))

    # 钉钉通知
    webhook = notify_config.get("dingtalk", {}).get("webhook", "")
    if notify_config.get("dingtalk", {}).get("enabled", False) and webhook:
        mgr.register("dingtalk", DingtalkNotifier(webhook))

    return mgr


def run_selfcheck(config: dict, storage: Storage, collector: DataCollector) -> None:
    """启动自检：检查数据源连通性、数据库完整性、配置有效性、交易日历

    所有检查失败仅记录日志，不阻止系统启动。

    Args:
        config: 完整配置字典
        storage: 数据存储实例
        collector: 数据采集器实例
    """
    results = []  # 汇总检查结果

    # 1. 检查数据源连通性
    try:
        collector.fetch_lof_fund_list()
        results.append(("数据源连通性", "PASS"))
    except Exception as e:
        logger.warning("自检-数据源连通性异常: %s", e)
        results.append(("数据源连通性", "FAIL: %s" % e))

    # 2. 检查SQLite完整性
    try:
        cursor = storage._conn.execute("PRAGMA integrity_check")
        row = cursor.fetchone()
        integrity_result = row[0] if row else ""
        if integrity_result == "ok":
            results.append(("SQLite完整性", "PASS"))
        else:
            logger.error("自检-SQLite完整性异常: %s", integrity_result)
            results.append(("SQLite完整性", "FAIL: %s" % integrity_result))
    except Exception as e:
        logger.error("自检-SQLite完整性检查失败: %s", e)
        results.append(("SQLite完整性", "FAIL: %s" % e))

    # 3. 检查配置有效性
    try:
        errors = validate_config(config)
        if not errors:
            results.append(("配置有效性", "PASS"))
        else:
            for err in errors:
                logger.error("自检-配置校验失败: %s", err)
            results.append(("配置有效性", "FAIL: %s" % "; ".join(errors)))
    except Exception as e:
        logger.error("自检-配置校验异常: %s", e)
        results.append(("配置有效性", "FAIL: %s" % e))

    # 4. 检查交易日历数据
    try:
        cursor = storage._conn.execute("SELECT COUNT(*) FROM holiday_calendar")
        row = cursor.fetchone()
        count = row[0] if row else 0
        if count > 0:
            results.append(("交易日历数据", "PASS (%d条)" % count))
        else:
            logger.warning("自检-交易日历表为空，首次运行属正常情况")
            results.append(("交易日历数据", "WARN: 表为空"))
    except Exception as e:
        logger.warning("自检-交易日历检查异常: %s", e)
        results.append(("交易日历数据", "WARN: %s" % e))

    # 汇总输出
    logger.info("===== 启动自检结果 =====")
    for name, result in results:
        logger.info("  %s: %s", name, result)
    logger.info("===== 自检完成 =====")


def main():
    """系统主入口：加载配置、初始化各模块、注册策略并启动调度器"""
    # 加载配置
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)

    # 初始化数据库
    db_dir = Path("db")
    db_dir.mkdir(exist_ok=True)
    conn = setup_database(str(db_dir / "get_cash.db"))
    storage = Storage(conn)

    # 初始化交易日历
    calendar = TradingCalendar()
    calendar.load_from_storage(storage)

    # 初始化通知管理器
    notifier = setup_notifier(config)

    # 初始化数据采集器
    collector = DataCollector(storage, config.get("data_source", {}))

    # 初始化调度器
    scheduler = StrategyScheduler(calendar)

    # 读取策略开关配置
    strategy_config = config.get("strategies", {})

    # 创建可转债打新策略实例
    bond_ipo = BondIpoStrategy(
        config.get("bond_ipo", {}),
        storage, notifier,
    )
    # 注入数据采集器
    bond_ipo._collector = collector

    # 创建逆回购策略实例（需要额外的 calendar 参数）
    reverse_repo = ReverseRepoStrategy(
        config.get("reverse_repo", {}),
        storage, notifier, calendar,
    )

    # 创建可转债配债策略实例
    bond_alloc = BondAllocationStrategy(
        config.get("bond_allocation", {}),
        storage, notifier,
    )

    # 注册已启用的策略
    for name, strat in [
        ("bond_ipo", bond_ipo),
        ("reverse_repo", reverse_repo),
        ("bond_allocation", bond_alloc),
    ]:
        if strategy_config.get(name, {}).get("enabled", True):
            scheduler.register(strat)

    # 添加每日定时任务
    scheduler.add_daily_job("bond_ipo", 9, 30)
    scheduler.add_daily_job("reverse_repo", 14, 30)
    scheduler.add_daily_job("bond_allocation", 9, 0)

    # 启动自检
    if config.get("system", {}).get("startup_selfcheck", True):
        run_selfcheck(config, storage, collector)

    # 注册心跳任务
    heartbeat_interval = config.get("system", {}).get("heartbeat_interval", 300)
    scheduler.add_heartbeat_job(heartbeat_interval)

    logger.info("系统启动完成")
    scheduler.start()


if __name__ == "__main__":
    main()
