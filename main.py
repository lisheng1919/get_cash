import logging
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path

from config_loader import load_config, validate_config
from config_manager import ConfigManager
from dashboard.app import create_app
from data.models import init_db
from data.storage import Storage
from data.collector import DataCollector
from scheduler.calendar import TradingCalendar
from scheduler.scheduler import StrategyScheduler
from strategies.bond_ipo import BondIpoStrategy
from strategies.reverse_repo import ReverseRepoStrategy
from strategies.bond_allocation import BondAllocationStrategy
from strategies.lof_premium.strategy import LofPremiumStrategy
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
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)
    return conn


def setup_notifier(config: dict, storage=None) -> NotificationManager:
    """根据配置初始化通知管理器，注册已启用的通知渠道

    Args:
        config: 完整配置字典

    Returns:
        已注册通知渠道的通知管理器
    """
    notify_config = config.get("notify", {})
    dual_events = notify_config.get("dual_channel_events", [])
    mgr = NotificationManager(notify_config, dual_channel_events=dual_events, storage=storage)

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

    # 持久化自检结果到告警事件 + system_status
    for name, result in results:
        if result == "PASS":
            storage.insert_alert_event("OK", "selfcheck", "%s: %s" % (name, result))
        elif result.startswith("FAIL"):
            storage.insert_alert_event("ERROR", "selfcheck", "%s: %s" % (name, result))
        elif result.startswith("WARN"):
            storage.insert_alert_event("WARN", "selfcheck", "%s: %s" % (name, result))
    all_pass = all(r == "PASS" for _, r in results)
    storage.upsert_system_status("selfcheck_result", "all_passed" if all_pass else "has_failures")

    # 汇总输出
    logger.info("===== 启动自检结果 =====")
    for name, result in results:
        logger.info("  %s: %s", name, result)
    logger.info("===== 自检完成 =====")


def auto_mute_funds(config: dict, storage: Storage, collector: DataCollector) -> None:
    """系统启动时自动静默无法申购或无套利空间的LOF基金

    Args:
        config: 完整配置字典
        storage: 数据存储实例
        collector: 数据采集器实例
    """
    lof_config = config.get("lof_premium", {})
    if not lof_config.get("auto_mute_enabled", True):
        logger.info("自动静默功能未启用，跳过")
        return

    # 获取申购状态
    try:
        purchase_status = collector.fetch_lof_purchase_status()
    except Exception as ex:
        logger.error("获取LOF申购状态失败，跳过自动静默: %s", ex)
        return

    if not purchase_status:
        logger.info("无LOF申购状态数据，跳过自动静默")
        return

    from datetime import timedelta

    auto_mute_paused_days = lof_config.get("auto_mute_paused_days", 30)
    min_profit_yuan = lof_config.get("min_profit_yuan", 200)
    available_capital = lof_config.get("available_capital", 100000)
    sell_commission_rate = lof_config.get("sell_commission_rate", 0.0003)

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    paused_muted = 0
    profit_muted = 0

    for code, info in purchase_status.items():
        fund_name = info.get("fund_name", "")

        # 检查是否已有手动静默（不覆盖）
        existing = storage.get_lof_fund(code)
        if existing and existing.get("status") == "muted":
            reason = existing.get("mute_reason", "")
            if reason.startswith("手动静默"):
                continue
            # 已静默且未到期，不重复处理
            muted_until = existing.get("muted_until", "")
            if muted_until and muted_until > now_str:
                continue

        # 规则1：暂停申购 → 静默30天
        if info["purchase_status"] == "暂停申购":
            # 先确保基金存在于lof_fund表
            if not existing:
                storage.upsert_lof_fund(code, fund_name, status="normal", is_suspended=False, daily_volume=0.0)
            muted_until = (now + timedelta(days=auto_mute_paused_days)).strftime("%Y-%m-%d %H:%M:%S")
            storage.mute_fund(code, muted_until, "暂停申购")
            paused_muted += 1
            continue

        # 规则2：限大额 → 计算套利利润
        if info["purchase_status"] == "限大额" and info["purchase_limit"] > 0:
            # 获取最近溢价率
            premium_rate = 3.0  # 默认假设值
            if existing:
                history = storage.get_premium_history(code, limit=1)
                if history:
                    premium_rate = abs(history[0].get("premium_rate", 3.0))

            net_profit = LofPremiumStrategy.calculate_arbitrage_profit(
                premium_rate=premium_rate,
                purchase_limit=info["purchase_limit"],
                available_capital=available_capital,
                purchase_fee_rate=info["purchase_fee_rate"],
                sell_commission_rate=sell_commission_rate,
            )

            if net_profit < min_profit_yuan:
                if not existing:
                    storage.upsert_lof_fund(code, fund_name, status="normal", is_suspended=False, daily_volume=0.0)
                # 限大额静默到当天结束
                today_end = now.strftime("%Y-%m-%d") + " 23:59:59"
                storage.mute_fund(code, today_end, "套利利润不足(¥%.0f)" % net_profit)
                profit_muted += 1

    logger.info("自动静默完成: 暂停申购%d只, 利润不足%d只", paused_muted, profit_muted)


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

    # 初始化配置管理器
    config_manager = ConfigManager(storage, scheduler=None, config_dict=config)

    # 初始化交易日历
    calendar = TradingCalendar()
    calendar.load_from_storage(storage)

    # 交易日历为空时自动从akshare同步
    cursor = conn.execute("SELECT COUNT(*) FROM holiday_calendar")
    holiday_count = cursor.fetchone()[0]
    if holiday_count == 0:
        logger.info("交易日历为空，开始从akshare自动同步...")
        try:
            calendar.sync_from_akshare(storage)
        except Exception as e:
            logger.warning("交易日历自动同步失败，系统将继续运行: %s", e)

    # 初始化通知管理器
    notifier = setup_notifier(config, storage=storage)

    # 初始化数据采集器
    collector = DataCollector(storage, config.get("data_source", {}), notifier=notifier)

    # 初始化调度器
    slow_threshold = config.get("system", {}).get("slow_threshold_ms", 30000)
    scheduler = StrategyScheduler(calendar, storage=storage, slow_threshold_ms=slow_threshold)
    config_manager._scheduler = scheduler

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
    # 注入数据采集器
    bond_alloc._collector = collector

    # 创建LOF溢价策略实例
    lof_premium = LofPremiumStrategy(
        config.get("lof_premium", {}),
        storage, notifier,
    )
    # 注入数据采集器
    lof_premium._collector = collector

    # 注册策略到配置管理器（支持热加载）
    config_manager.register_strategy("bond_ipo", bond_ipo)
    config_manager.register_strategy("reverse_repo", reverse_repo)
    config_manager.register_strategy("bond_allocation", bond_alloc)
    config_manager.register_strategy("lof_premium", lof_premium)

    # 从yaml初始化配置到数据库（仅首次启动时执行）
    config_manager.init_from_yaml()

    # 注册已启用的策略
    for name, strat in [
        ("bond_ipo", bond_ipo),
        ("reverse_repo", reverse_repo),
        ("bond_allocation", bond_alloc),
        ("lof_premium", lof_premium),
    ]:
        if strategy_config.get(name, {}).get("enabled", True):
            scheduler.register(strat)

    # 添加每日定时任务
    scheduler.add_daily_job("bond_ipo", 9, 30)
    scheduler.add_daily_job("reverse_repo", 14, 30)
    scheduler.add_daily_job("bond_allocation", 9, 0)

    # LOF溢价策略使用间隔轮询
    lof_premium_interval = config.get("lof_premium", {}).get("poll_interval", 5)
    if strategy_config.get("lof_premium", {}).get("enabled", True):
        scheduler.add_interval_job("lof_premium", lof_premium_interval)

    # 持久化系统启动时间
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    storage.upsert_system_status("start_time", start_time)
    strategy_names = [name for name, _ in [
        ("bond_ipo", bond_ipo), ("reverse_repo", reverse_repo),
        ("bond_allocation", bond_alloc), ("lof_premium", lof_premium),
    ] if strategy_config.get(name, {}).get("enabled", True)]
    storage.insert_alert_event("INFO", "system", "系统启动，策略: %s" % ", ".join(strategy_names))

    # 自动静默无法申购的LOF基金
    auto_mute_funds(config, storage, collector)

    # 启动自检
    if config.get("system", {}).get("startup_selfcheck", True):
        run_selfcheck(config, storage, collector)

    # 注册心跳任务
    heartbeat_interval = config.get("system", {}).get("heartbeat_interval", 300)
    scheduler.add_heartbeat_job(heartbeat_interval)

    # 添加配置轮询任务（每30秒检查重载信号）
    scheduler.add_config_poll_job(config_manager, interval=30)

    # 静默过期基金自动清理（每小时检查一次）
    def cleanup_expired_mutes():
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        expired = conn.execute(
            "SELECT code FROM lof_fund WHERE status='muted' AND muted_until < ? AND muted_until != ''",
            (now_str,),
        ).fetchall()
        for row in expired:
            storage.unmute_fund(row["code"])
        if expired:
            logger.info("自动清理%d只过期静默基金", len(expired))

    scheduler._scheduler.add_job(cleanup_expired_mutes, 'interval', hours=1, id='cleanup_expired_mutes')

    # 启动Flask看板线程
    flask_app = create_app(storage=storage, config_manager=config_manager)
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=5000, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    logger.info("Flask看板已启动于 http://0.0.0.0:5000")

    logger.info("系统启动完成")
    scheduler.start()


if __name__ == "__main__":
    main()
