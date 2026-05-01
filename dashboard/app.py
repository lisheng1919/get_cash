"""统一看板 Flask 应用 — API模式

重构为工厂函数模式，提供RESTful API供前端SPA调用。
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, g, jsonify, render_template, request

from data.models import init_db
from data.storage import Storage

# 数据库路径：相对于项目根目录
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "db",
    "get_cash.db",
)


def create_app(storage=None, config_manager=None):
    """Flask应用工厂函数

    Args:
        storage: 可选的Storage实例，由main.py注入
        config_manager: 可选的ConfigManager实例，由main.py注入

    Returns:
        配置好的Flask应用
    """
    app = Flask(__name__)
    # 存储注入的依赖，供_get_storage使用
    app.config["STORAGE"] = storage
    app.config["CONFIG_MANAGER"] = config_manager

    # 注册teardown：关闭per-request创建的DB连接
    app.teardown_appcontext(close_db)

    # ==================== 辅助函数 ====================

    def _get_storage():
        """获取Storage实例

        优先使用注入的storage；否则通过Flask g对象管理per-request连接。
        """
        # 优先使用注入的storage（含已初始化的DB连接）
        injected = app.config.get("STORAGE")
        if injected is not None:
            return injected

        # per-request连接管理：同一请求内复用
        if "storage" not in g:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            init_db(conn)
            g.storage = Storage(conn)
        return g.storage

    def _get_config_manager():
        """获取ConfigManager实例"""
        return app.config.get("CONFIG_MANAGER")

    # ==================== 页面路由 ====================

    @app.route("/")
    def index():
        """看板首页，SPA入口"""
        return render_template("index.html")

    # ==================== 状态API ====================

    @app.route("/api/status")
    def api_status():
        """系统状态总览API，支持告警和通知分页"""
        storage = _get_storage()

        # 系统健康信息
        start_time_str = storage.get_system_status("start_time") or ""
        uptime_seconds = 0
        if start_time_str:
            try:
                start_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
                uptime_seconds = int((datetime.now() - start_dt).total_seconds())
            except ValueError:
                pass

        # 自检结果
        selfcheck = storage.get_system_status("selfcheck_result") or "unknown"

        # 最近心跳时间
        last_heartbeat = ""
        hb_rows = storage._conn.execute(
            "SELECT timestamp FROM alert_event WHERE source='heartbeat' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchall()
        if hb_rows:
            last_heartbeat = hb_rows[0]["timestamp"]

        # 数据源状态
        data_sources = storage._conn.execute(
            "SELECT * FROM data_source_status ORDER BY name"
        ).fetchall()
        data_sources = [dict(r) for r in data_sources]

        # 通知渠道今日统计（使用范围查询替代LIKE）
        today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
        tomorrow_start = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        stats_row = storage._conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success_cnt, "
            "SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) as fail_cnt "
            "FROM notification_log WHERE timestamp >= ? AND timestamp < ?",
            (today_start, tomorrow_start),
        ).fetchone()
        today_stats = {
            "total": stats_row["total"] or 0,
            "success": stats_row["success_cnt"] or 0,
            "fail": stats_row["fail_cnt"] or 0,
        }

        # 策略执行概况（每个策略最近一次 + 今日执行次数）
        strategy_rows = storage._conn.execute(
            "SELECT strategy_name, trigger_time AS last_trigger_time, "
            "status AS last_status, duration_ms AS last_duration_ms "
            "FROM strategy_execution_log "
            "WHERE id IN (SELECT MAX(id) FROM strategy_execution_log GROUP BY strategy_name) "
            "ORDER BY strategy_name"
        ).fetchall()
        strategy_execution = [dict(r) for r in strategy_rows]
        for se in strategy_execution:
            cnt_row = storage._conn.execute(
                "SELECT COUNT(*) as cnt FROM strategy_execution_log "
                "WHERE strategy_name=? AND trigger_time >= ? AND trigger_time < ?",
                (se["strategy_name"], today_start, tomorrow_start),
            ).fetchone()
            se["today_count"] = cnt_row["cnt"]

        # 执行耗时趋势（LOF溢价最近20次）
        execution_trend = [dict(r) for r in storage._conn.execute(
            "SELECT trigger_time, duration_ms FROM strategy_execution_log "
            "WHERE strategy_name='lof_premium' "
            "ORDER BY trigger_time DESC LIMIT 20"
        ).fetchall()]

        # 告警事件（分页）
        alert_page = request.args.get("alert_page", 1, type=int)
        alert_page_size = request.args.get("alert_page_size", 10, type=int)
        alert_search = request.args.get("alert_search")
        alert_events = storage.query_paginated(
            "alert_event", page=alert_page, page_size=alert_page_size,
            order_by="timestamp", order_dir="DESC",
            search=alert_search, search_columns=["level", "source", "message"] if alert_search else None,
        )

        # 通知记录（分页）
        notif_page = request.args.get("notif_page", 1, type=int)
        notif_page_size = request.args.get("notif_page_size", 10, type=int)
        notif_search = request.args.get("notif_search")
        notification_logs = storage.query_paginated(
            "notification_log", page=notif_page, page_size=notif_page_size,
            order_by="timestamp", order_dir="DESC",
            search=notif_search, search_columns=["channel", "status", "event_type"] if notif_search else None,
        )

        return jsonify({
            "system": {
                "status": "running",
                "uptime_seconds": uptime_seconds,
                "selfcheck": selfcheck,
                "last_heartbeat": last_heartbeat,
            },
            "data_sources": data_sources,
            "notifications": {
                "today_stats": today_stats,
            },
            "strategy_execution": strategy_execution,
            "execution_trend": execution_trend,
            "alert_events": alert_events,
            "notification_logs": notification_logs,
        })

    # ==================== 业务数据API ====================

    @app.route("/api/data/lof_premium")
    def api_data_lof_premium():
        """LOF溢价率监控 - 分页查询"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "timestamp")
        sort_order = request.args.get("sort_order", "DESC")
        return jsonify(storage.query_paginated(
            "premium_history",
            page=page, page_size=page_size,
            search=search, search_columns=["fund_code", "iopv_source"],
            order_by=sort_by, order_dir=sort_order,
        ))

    @app.route("/api/data/trade_signal")
    def api_data_trade_signal():
        """LOF套利信号 - 分页查询"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "trigger_time")
        sort_order = request.args.get("sort_order", "DESC")
        return jsonify(storage.query_paginated(
            "trade_signal",
            page=page, page_size=page_size,
            search=search, search_columns=["fund_code", "action", "status"],
            order_by=sort_by, order_dir=sort_order,
        ))

    @app.route("/api/data/bond_ipo")
    def api_data_bond_ipo():
        """可转债打新 - 分页查询"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "subscribe_date")
        sort_order = request.args.get("sort_order", "DESC")
        return jsonify(storage.query_paginated(
            "bond_ipo",
            page=page, page_size=page_size,
            search=search, search_columns=["code", "name"],
            order_by=sort_by, order_dir=sort_order,
        ))

    @app.route("/api/data/bond_allocation")
    def api_data_bond_allocation():
        """可转债配债 - 分页查询"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "record_date")
        sort_order = request.args.get("sort_order", "DESC")
        return jsonify(storage.query_paginated(
            "bond_allocation",
            page=page, page_size=page_size,
            search=search, search_columns=["code", "stock_name"],
            order_by=sort_by, order_dir=sort_order,
        ))

    @app.route("/api/data/reverse_repo")
    def api_data_reverse_repo():
        """逆回购记录 - 分页查询"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "date")
        sort_order = request.args.get("sort_order", "DESC")
        return jsonify(storage.query_paginated(
            "reverse_repo",
            page=page, page_size=page_size,
            search=search, search_columns=["date", "code"],
            order_by=sort_by, order_dir=sort_order,
        ))

    @app.route("/api/data/daily_summary")
    def api_data_daily_summary():
        """每日汇总 - 分页查询"""
        storage = _get_storage()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "date")
        sort_order = request.args.get("sort_order", "DESC")
        return jsonify(storage.query_paginated(
            "daily_summary",
            page=page, page_size=page_size,
            search=search, search_columns=["date", "strategy_type"],
            order_by=sort_by, order_dir=sort_order,
        ))

    # ==================== 静默API ====================

    @app.route("/api/cleanup_expired_mutes", methods=["POST"])
    def api_cleanup_expired_mutes():
        """清理已过期的静默基金，恢复为normal状态"""
        storage = _get_storage()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = storage._conn.execute(
            "SELECT code FROM lof_fund WHERE status='muted' AND muted_until < ? AND muted_until != ''",
            (now_str,),
        )
        expired_codes = [row["code"] for row in cursor.fetchall()]
        for code in expired_codes:
            storage.unmute_fund(code)
        return jsonify({"ok": True, "restored": len(expired_codes)})

    @app.route("/api/mute", methods=["POST"])
    def api_mute():
        """手动静默基金"""
        data = request.get_json(force=True)
        fund_code = data.get("fund_code", "")
        days = data.get("days", 7)

        if not fund_code:
            return jsonify({"ok": False, "error": "fund_code必填"}), 400

        # days参数校验
        try:
            days = int(days)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "days必须为整数"}), 400
        if days < 1 or days > 365:
            return jsonify({"ok": False, "error": "days必须在1-365范围内"}), 400

        storage = _get_storage()
        fund = storage.get_lof_fund(fund_code)
        if not fund:
            return jsonify({"ok": False, "error": "基金不存在"}), 404

        muted_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        storage.mute_fund(fund_code, muted_until, "手动静默")
        return jsonify({"ok": True, "muted_until": muted_until})

    @app.route("/api/unmute", methods=["POST"])
    def api_unmute():
        """解除基金静默"""
        data = request.get_json(force=True)
        fund_code = data.get("fund_code", "")

        if not fund_code:
            return jsonify({"ok": False, "error": "fund_code必填"}), 400

        storage = _get_storage()
        storage.unmute_fund(fund_code)
        return jsonify({"ok": True})

    @app.route("/api/muted_funds")
    def api_muted_funds():
        """获取静默基金列表 - 分页查询（自动清理过期静默）"""
        storage = _get_storage()
        # 自动清理已过期的静默基金
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        expired = storage._conn.execute(
            "SELECT code FROM lof_fund WHERE status='muted' AND muted_until < ? AND muted_until != ''",
            (now_str,),
        ).fetchall()
        for row in expired:
            storage.unmute_fund(row["code"])

        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 10, type=int)
        search = request.args.get("search")
        return jsonify(storage.query_paginated(
            "lof_fund",
            page=page, page_size=page_size,
            search=search, search_columns=["code", "name"],
            order_by="muted_until", order_dir="ASC",
            extra_where="status='muted'",
        ))

    # ==================== 配置API ====================

    # 敏感配置键列表
    SENSITIVE_KEYS = {"serverchan_key", "webhook"}

    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        """查询配置项

        Query参数:
            category: 可选，按分类过滤
        """
        cm = _get_config_manager()
        if cm is None:
            return jsonify({"ok": False, "error": "ConfigManager未初始化"}), 503

        category = request.args.get("category")
        items = cm.get_config(category)
        # 敏感字段脱敏：仅显示后4位
        for item in items:
            if item["key"] in SENSITIVE_KEYS and item["value"]:
                val = item["value"]
                if len(val) > 4:
                    item["value"] = "****" + val[-4:]
                else:
                    item["value"] = "****"
        return jsonify({"ok": True, "items": items})

    @app.route("/api/config", methods=["PUT"])
    def api_config_update():
        """批量更新配置

        JSON Body: {"items": [{"category", "section", "key", "value"}]}
        """
        cm = _get_config_manager()
        if cm is None:
            return jsonify({"ok": False, "error": "ConfigManager未初始化"}), 503

        data = request.get_json(force=True)
        items = data.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "items不能为空"}), 400

        # 过滤掉脱敏格式的值（****开头的），不覆盖原值
        real_items = []
        for item in items:
            if item["key"] in SENSITIVE_KEYS and isinstance(item.get("value"), str) and item["value"].startswith("****"):
                continue
            real_items.append(item)

        if real_items:
            cm.update_config(real_items)
        return jsonify({"ok": True, "updated": len(real_items)})

    @app.route("/api/config/reload", methods=["POST"])
    def api_config_reload():
        """手动触发配置重载"""
        cm = _get_config_manager()
        if cm is None:
            return jsonify({"ok": False, "error": "ConfigManager未初始化"}), 503

        cm.reload()
        return jsonify({"ok": True})

    return app


def close_db(exception):
    """Teardown函数：关闭per-request创建的DB连接"""
    storage = g.pop("storage", None)
    if storage is not None:
        storage._conn.close()


if __name__ == "__main__":
    # 独立运行时自动创建Storage和ConfigManager
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    storage = Storage(conn)

    # 尝试加载config.yaml初始化ConfigManager
    config_manager = None
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.yaml",
        )
        if os.path.exists(config_path):
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            from config_manager import ConfigManager
            config_manager = ConfigManager(storage, scheduler=None, config_dict=config)
            config_manager.init_from_yaml()
    except Exception as e:
        print(f"警告: ConfigManager初始化失败({e})，配置管理功能不可用")

    create_app(storage=storage, config_manager=config_manager).run(debug=True, port=5000)
