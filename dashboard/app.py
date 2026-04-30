"""统一看板 Flask 应用"""

from flask import Flask, render_template, request, jsonify
import sqlite3
import os
import json
from datetime import datetime
from data.storage import Storage

app = Flask(__name__)

# 数据库路径：相对于项目根目录
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "get_cash.db")


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/api/status")
def api_status():
    """状态总览API，返回JSON"""
    conn = get_db()

    # 系统健康
    start_time_str = ""
    cursor = conn.execute("SELECT value FROM system_status WHERE key = 'start_time'")
    row = cursor.fetchone()
    if row:
        start_time_str = row["value"] if hasattr(row, 'keys') else row[0]
    uptime_seconds = 0
    if start_time_str:
        try:
            start_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            uptime_seconds = int((datetime.now() - start_dt).total_seconds())
        except ValueError:
            pass

    # 自检结果
    selfcheck = "unknown"
    cursor = conn.execute("SELECT value FROM system_status WHERE key = 'selfcheck_result'")
    row = cursor.fetchone()
    if row:
        selfcheck = row["value"] if hasattr(row, 'keys') else row[0]

    # 数据源状态
    data_sources = [dict(r) for r in conn.execute(
        "SELECT * FROM data_source_status ORDER BY name"
    ).fetchall()]

    # 策略执行概况（每个策略最近一次）
    strategy_execution = [dict(r) for r in conn.execute(
        """SELECT strategy_name, trigger_time AS last_trigger_time,
                  status AS last_status, duration_ms AS last_duration_ms
           FROM strategy_execution_log
           WHERE id IN (SELECT MAX(id) FROM strategy_execution_log GROUP BY strategy_name)
           ORDER BY strategy_name"""
    ).fetchall()]

    # 今日执行次数
    today_str = datetime.now().strftime("%Y-%m-%d")
    for se in strategy_execution:
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM strategy_execution_log WHERE strategy_name=? AND trigger_time LIKE ?",
            (se["strategy_name"], today_str + "%"),
        )
        cnt_row = cursor.fetchone()
        se["today_count"] = cnt_row["cnt"] if hasattr(cnt_row, 'keys') else cnt_row[0]

    # 执行耗时趋势（LOF溢价最近20次）
    execution_trend = [dict(r) for r in conn.execute(
        """SELECT trigger_time, duration_ms FROM strategy_execution_log
           WHERE strategy_name='lof_premium'
           ORDER BY trigger_time DESC LIMIT 20"""
    ).fetchall()]

    # 告警事件
    alert_events = [dict(r) for r in conn.execute(
        "SELECT * FROM alert_event ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()]

    # 通知记录
    notification_logs = [dict(r) for r in conn.execute(
        "SELECT * FROM notification_log ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()]

    # 通知渠道统计
    cursor = conn.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success_cnt,
                  SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) as fail_cnt
           FROM notification_log WHERE timestamp LIKE ?""",
        (today_str + "%",),
    )
    stats_row = cursor.fetchone()
    if hasattr(stats_row, 'keys'):
        today_stats = {"total": stats_row["total"] or 0, "success": stats_row["success_cnt"] or 0, "fail": stats_row["fail_cnt"] or 0}
    else:
        today_stats = {"total": stats_row[0] or 0, "success": stats_row[1] or 0, "fail": stats_row[2] or 0}

    # 最近心跳时间
    last_heartbeat = ""
    cursor = conn.execute(
        "SELECT timestamp FROM alert_event WHERE source='heartbeat' ORDER BY timestamp DESC LIMIT 1"
    )
    hb_row = cursor.fetchone()
    if hb_row:
        last_heartbeat = hb_row["timestamp"] if hasattr(hb_row, 'keys') else hb_row[0]

    conn.close()

    return json.dumps({
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
    }, ensure_ascii=False, default=str)


@app.route("/api/mute", methods=["POST"])
def api_mute():
    """手动静默基金"""
    data = request.get_json(force=True)
    fund_code = data.get("fund_code", "")
    days = data.get("days", 7)

    if not fund_code:
        return jsonify({"ok": False, "error": "fund_code必填"}), 400

    conn = get_db()
    storage = Storage(conn)
    # 确保基金存在
    fund = storage.get_lof_fund(fund_code)
    if not fund:
        conn.close()
        return jsonify({"ok": False, "error": "基金不存在"}), 404

    from datetime import timedelta
    muted_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    storage.mute_fund(fund_code, muted_until, "手动静默")
    conn.close()
    return jsonify({"ok": True, "muted_until": muted_until})


@app.route("/api/unmute", methods=["POST"])
def api_unmute():
    """解除基金静默"""
    data = request.get_json(force=True)
    fund_code = data.get("fund_code", "")

    if not fund_code:
        return jsonify({"ok": False, "error": "fund_code必填"}), 400

    conn = get_db()
    storage = Storage(conn)
    storage.unmute_fund(fund_code)
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/muted_funds")
def api_muted_funds():
    """获取所有静默中的基金列表"""
    conn = get_db()
    storage = Storage(conn)
    muted = storage.list_muted_funds()
    conn.close()
    # 只返回关键字段
    result = []
    for f in muted:
        result.append({
            "code": f["code"],
            "name": f["name"],
            "mute_reason": f["mute_reason"],
            "muted_until": f["muted_until"],
        })
    return jsonify(result)


@app.route("/")
def index():
    """统一看板首页"""
    conn = get_db()

    # 构建业务数据段（供业务数据Tab使用）
    data_sections = [
        {
            "title": "LOF溢价率监控",
            "columns": ["timestamp", "fund_code", "price", "iopv", "premium_rate", "iopv_source", "action"],
            "rows": [dict(r, action='<button class="mute-btn" data-code="' + str(r["fund_code"]) + '">静默</button>') for r in conn.execute(
                "SELECT * FROM premium_history ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "LOF套利信号",
            "columns": ["id", "trigger_time", "fund_code", "premium_rate", "action", "status", "iopv_source"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM trade_signal ORDER BY trigger_time DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "可转债打新",
            "columns": ["code", "name", "subscribe_date", "winning_result", "payment_status", "listing_date", "sell_status"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM bond_ipo ORDER BY subscribe_date DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "可转债配债",
            "columns": ["code", "stock_code", "stock_name", "content_weight", "safety_cushion", "record_date", "payment_date", "listing_date", "status", "actual_slippage"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM bond_allocation ORDER BY record_date DESC LIMIT 20"
            ).fetchall()],
        },
        {
            "title": "逆回购记录",
            "columns": ["id", "date", "code", "rate", "amount", "due_date", "profit"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM reverse_repo ORDER BY date DESC LIMIT 10"
            ).fetchall()],
        },
        {
            "title": "每日汇总",
            "columns": ["id", "date", "strategy_type", "profit", "action_log"],
            "rows": [dict(r) for r in conn.execute(
                "SELECT * FROM daily_summary ORDER BY date DESC LIMIT 30"
            ).fetchall()],
        },
    ]

    conn.close()
    return render_template("index.html", data_sections=data_sections)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
