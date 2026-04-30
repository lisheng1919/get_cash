"""统一看板 Flask 应用"""

from flask import Flask, render_template
import sqlite3
import os

app = Flask(__name__)

# 数据库路径：相对于项目根目录
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "get_cash.db")


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    """统一看板首页，展示各策略模块的最新数据"""
    conn = get_db()
    # LOF溢价历史：最近20条（实时溢价率监控）
    premium_history = conn.execute(
        "SELECT * FROM premium_history ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()
    # LOF套利信号：最近20条
    signals = conn.execute(
        "SELECT * FROM trade_signal ORDER BY trigger_time DESC LIMIT 20"
    ).fetchall()
    # 可转债打新：最近20条
    bond_ipos = conn.execute(
        "SELECT * FROM bond_ipo ORDER BY subscribe_date DESC LIMIT 20"
    ).fetchall()
    # 可转债配债：最近20条
    allocations = conn.execute(
        "SELECT * FROM bond_allocation ORDER BY record_date DESC LIMIT 20"
    ).fetchall()
    # 逆回购记录：最近10条
    repos = conn.execute(
        "SELECT * FROM reverse_repo ORDER BY date DESC LIMIT 10"
    ).fetchall()
    # 每日汇总：最近30条
    summaries = conn.execute(
        "SELECT * FROM daily_summary ORDER BY date DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return render_template(
        "index.html",
        premium_history=premium_history,
        signals=signals,
        bond_ipos=bond_ipos,
        allocations=allocations,
        repos=repos,
        summaries=summaries,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
