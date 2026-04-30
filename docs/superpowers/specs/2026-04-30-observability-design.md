# 系统可观测性增强设计

> 日期: 2026-04-30
> 状态: 设计完成，待实施

## 背景

系统运行后"无感"，运维人员无法直观判断系统是否正常运行、数据源是否健康、异常切换是否发生。具体痛点：

1. 不知道系统是否活着 — 心跳只打一行策略名列表日志，无诊断价值
2. 数据源异常不可见 — 只有 lof_list 接入了状态记录，其他5个数据源失败只写日志
3. 看板信息不够 — 只有业务数据表格，无系统状态/执行历史/告警信息
4. 通知不够及时/全面 — data_source_failure 事件定义了但从未触发，通知发送失败静默吞异常

## 设计目标

- 看板能一眼判断系统是否正常
- 数据源异常（失败、切换、恢复）全程可追踪
- 策略执行结果、耗时、异常可回溯
- 通知发送成功/失败有记录
- 告警事件集中展示，不散落在日志中

## 看板改造：双标签页

### 导航结构

顶部 Tab 切换：`状态总览` | `业务数据`，默认展示状态总览。

### 状态总览页（7个区块）

**第一行：3个状态卡片**

| 区块 | 内容 | 数据来源 |
|------|------|----------|
| 系统健康 | 运行状态、运行时长、策略启用数、上次心跳时间、自检结果 | 内存(启动时间) + data_source_status + alert_event |
| 数据源状态 | 6个数据源的实时状态(正常/失败/失败次数)、最后成功时间 | data_source_status |
| 通知渠道状态 | 各渠道启用状态、今日发送统计(成功/失败) | notification_log |

**第二行：执行概况 + 耗时趋势**

| 区块 | 内容 | 数据来源 |
|------|------|----------|
| 策略执行概况 | 表格：策略名/上次执行时间/结果/耗时/今日执行次数 | strategy_execution_log |
| 执行耗时趋势 | CSS柱状图：LOF溢价策略最近20次执行耗时，红色标注超阈值 | strategy_execution_log |

**第三行：告警流 + 通知记录**

| 区块 | 内容 | 数据来源 |
|------|------|----------|
| 告警事件流 | 按时间倒序，带级别标签(ERROR/WARN/INFO/OK)的事件列表 | alert_event |
| 通知发送记录 | 表格：时间/渠道/事件类型/发送状态 | notification_log |

### 业务数据页

保留原有内容不变（premium_history、trade_signal、bond_ipo、bond_allocation、reverse_repo、daily_summary），同样加自动刷新。

### 前端技术方案

- 自动刷新：JS `setInterval` 每60秒调用 Flask API
- 图表：纯CSS柱状图，不引入外部图表库
- Flask 新增 `/api/status` 接口返回 JSON，前端 AJAX 渲染，避免全页刷新闪烁

## 数据库变更

### 新增表

#### strategy_execution_log

```sql
CREATE TABLE IF NOT EXISTS strategy_execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name VARCHAR(50) NOT NULL DEFAULT '',
    trigger_time DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    status VARCHAR(10) NOT NULL DEFAULT 'success',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error_message VARCHAR(500) NOT NULL DEFAULT '',
    record_time DATETIME NOT NULL DEFAULT (datetime('now','localtime'))
);
```

- `status`: success / fail / skip
- `duration_ms`: 执行耗时毫秒数
- `error_message`: 失败时的错误摘要，截断到500字符

#### alert_event

```sql
CREATE TABLE IF NOT EXISTS alert_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level VARCHAR(10) NOT NULL DEFAULT 'INFO',
    source VARCHAR(50) NOT NULL DEFAULT '',
    message VARCHAR(500) NOT NULL DEFAULT '',
    timestamp DATETIME NOT NULL DEFAULT (datetime('now','localtime'))
);
```

- `level`: ERROR / WARN / INFO / OK
- `source`: 产生告警的模块，如 collector、scheduler、notifier、selfcheck

#### notification_log

```sql
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel VARCHAR(20) NOT NULL DEFAULT '',
    event_type VARCHAR(50) NOT NULL DEFAULT '',
    title VARCHAR(200) NOT NULL DEFAULT '',
    message VARCHAR(500) NOT NULL DEFAULT '',
    status VARCHAR(10) NOT NULL DEFAULT 'success',
    timestamp DATETIME NOT NULL DEFAULT (datetime('now','localtime'))
);
```

- `channel`: desktop / wechat / dingtalk
- `status`: success / fail

### 扩展现有表 data_source_status

新增字段：
- `last_failure_time DATETIME NOT NULL DEFAULT ''` — 上次失败时间
- `failure_reason VARCHAR(200) NOT NULL DEFAULT ''` — 失败原因

### Storage 层新增方法

- `insert_execution_log(strategy_name, status, duration_ms, error_message)` — 写入策略执行记录
- `insert_alert_event(level, source, message)` — 写入告警事件
- `insert_notification_log(channel, event_type, title, message, status)` — 写入通知记录
- `list_execution_logs(strategy_name, limit)` — 查询策略执行记录
- `list_alert_events(limit)` — 查询告警事件
- `list_notification_logs(limit)` — 查询通知记录
- `list_all_data_source_status()` — 列出所有数据源状态
- 扩展 `record_data_source_failure(name, reason)` — 在现有方法上增加 reason 参数（默认空串），写入 last_failure_time 和 failure_reason

## 后端改造

### DataCollector — 6个数据源全部接入状态记录

当前只有 `fetch_lof_fund_list` 接入了 `update_data_source_status` / `record_data_source_failure`。改造后：

| 方法 | 数据源名称 | 成功时 | 失败时 |
|------|-----------|--------|--------|
| fetch_lof_fund_list | lof_list | update_data_source_status("ok") | record_data_source_failure + 告警 |
| fetch_lof_iopv | lof_iopv | update_data_source_status("ok") | record_data_source_failure + 告警 |
| fetch_lof_realtime | lof_realtime | update_data_source_status("ok") | record_data_source_failure |
| fetch_bond_ipo_list | bond_ipo | update_data_source_status("ok") | record_data_source_failure + 告警 |
| fetch_bond_allocation_list | bond_alloc | update_data_source_status("ok") | record_data_source_failure + 告警 |
| fetch_reverse_repo_rate | reverse_repo | update_data_source_status("ok") | record_data_source_failure + 告警 |

连续失败达到 `max_consecutive_failures` 阈值时：
1. 写入 alert_event (level=ERROR)
2. 调用 `notifier.notify(event_type="data_source_failure")` 推送通知
3. DataCollector 构造函数新增 `notifier` 参数（可选，默认None），注入 NotificationManager 实例

### StrategyScheduler — 执行包装

`_daily_wrapper` 和 `_interval_wrapper` 改造：

```python
def _daily_wrapper():
    today = date.today()
    if not self._calendar.is_trading_day(today):
        # 记录跳过
        self._storage.insert_execution_log(strategy_name, "skip", 0, "非交易日")
        return
    start = time.perf_counter()
    try:
        strategy.execute()
        duration = int((time.perf_counter() - start) * 1000)
        self._storage.insert_execution_log(strategy_name, "success", duration, "")
    except Exception as ex:
        duration = int((time.perf_counter() - start) * 1000)
        self._storage.insert_execution_log(strategy_name, "fail", duration, str(ex)[:500])
        self._storage.insert_alert_event("ERROR", strategy_name, "策略执行失败: %s" % str(ex)[:200])
    # 耗时超过阈值告警
    if duration > self._slow_threshold_ms:
        self._storage.insert_alert_event("WARN", strategy_name, "策略执行耗时%dms超过阈值%dms" % (duration, self._slow_threshold_ms))
```

- `_slow_threshold_ms` 默认 30000 (30秒)，可通过 config.yaml 的 `system.slow_threshold_ms` 配置

### NotificationManager — 持久化 + 失败记录

1. 构造函数增加 `storage` 参数
2. `notify()` 方法每次调用后写入 `notification_log`，无论成功失败
3. 各渠道 `send()` 的异常不再静默吞掉，改为记录 status=fail + WARN 日志
4. `NotificationEvent` 枚举补入 `lof_premium`、`reverse_repo`、`bond_ipo`，与策略代码对齐

### 心跳增强

`add_heartbeat_job` 的心跳函数改造：

```python
def _heartbeat():
    # 汇总数据源状态
    ds_status = self._storage.list_all_data_source_status()
    unhealthy = [s for s in ds_status if s["status"] != "ok"]
    # 汇总策略执行状态
    # 写入健康摘要到 alert_event
    if unhealthy:
        self._storage.insert_alert_event("WARN", "heartbeat", "数据源异常: %s" % ", ".join(s["name"] for s in unhealthy))
    else:
        self._storage.insert_alert_event("INFO", "heartbeat", "系统正常运行，数据源全部OK")
    logger.info("系统心跳：正常运行中，数据源: %d/%d OK", len(ds_status) - len(unhealthy), len(ds_status))
```

### 系统启动/自检结果持久化

`run_selfcheck` 完成后，每项检查结果写入 `alert_event`：
- PASS → level=OK
- FAIL → level=ERROR
- WARN → level=WARN

系统启动时写入一条 INFO 告警：`"系统启动，版本: xxx, 策略: [list]"`

## Flask API

### GET /api/status

返回 JSON，包含状态总览页全部数据：

```json
{
  "system": {
    "status": "running",
    "uptime_seconds": 8132,
    "strategies_enabled": 4,
    "strategies_total": 4,
    "last_heartbeat": "2026-04-30 14:47:00",
    "selfcheck": "all_passed"
  },
  "data_sources": [
    {"name": "lof_list", "status": "ok", "last_success_time": "...", "consecutive_failures": 0, "last_failure_time": "", "failure_reason": ""},
    ...
  ],
  "notifications": {
    "channels": [
      {"name": "desktop", "enabled": true},
      {"name": "wechat", "enabled": false},
      {"name": "dingtalk", "enabled": false}
    ],
    "today_stats": {"total": 5, "success": 5, "fail": 0}
  },
  "strategy_execution": [
    {"strategy_name": "lof_premium", "last_trigger_time": "...", "last_status": "success", "last_duration_ms": 36000, "today_count": 12},
    ...
  ],
  "execution_trend": [
    {"trigger_time": "...", "duration_ms": 36000},
    ...
  ],
  "alert_events": [
    {"level": "ERROR", "source": "collector", "message": "...", "timestamp": "..."},
    ...
  ],
  "notification_logs": [
    {"channel": "desktop", "event_type": "lof_premium", "title": "...", "status": "success", "timestamp": "..."},
    ...
  ]
}
```

## 不改动的部分

- 策略核心逻辑（execute 内部）
- 交易层（TradeExecutor、RiskChecker）
- 配置文件结构（config.yaml）
- 原有业务数据页面内容

## 跨进程状态共享

main.py 和 dashboard/app.py 是两个独立进程，系统启动时间等运行时状态需持久化：

- 新增 `system_status` 表（单行），记录 `start_time`（系统启动时间）和 `selfcheck_result`（自检结果摘要）
- main.py 启动时写入 start_time，dashboard 读取后计算 uptime_seconds
- 自检完成后更新 selfcheck_result

```sql
CREATE TABLE IF NOT EXISTS system_status (
    key VARCHAR(50) PRIMARY KEY,
    value VARCHAR(500) NOT NULL DEFAULT ''
);
```

## 数据清理

strategy_execution_log、alert_event、notification_log 三张表按 `system.data_retention_days`（默认90天）定期清理，复用已有的数据清理逻辑。
