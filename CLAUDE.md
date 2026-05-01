# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

个人量化套利中枢系统 — Python 3.10+, 集成四个低风险套利策略：可转债打新、可转债配债、节假日逆回购、LOF底仓套利。SQLite持久化，APScheduler调度，miniQMT+xtquant执行交易（V1.3+）。看板使用Flask API + Petite-Vue SPA。

## Commands

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_config_manager.py -v

# 启动系统（含看板线程）
python main.py                          # 默认 config.yaml
python main.py path/to/config.yaml      # 自定义配置

# 独立启动看板（自动连接DB+加载配置）
python dashboard/app.py                 # http://localhost:5000

# 安装依赖
pip install -r requirements.txt
```

## Architecture

分层模块化架构，数据流自底向上：

```
Market APIs → DataCollector → Storage(SQLite) → StrategyScheduler → Strategy.execute() → Notifier/Trader
```

**核心依赖链**：每个策略继承 `BaseStrategy`，持有 `_storage`(Storage) 和 `_notifier`(NotificationManager)。`BondIpoStrategy` 额外需要 `_collector`(DataCollector) 属性注入；`ReverseRepoStrategy` 构造函数额外接收 `TradingCalendar`。

**数据层** (`data/`)：`models.py` 定义16张表DDL（`init_db`建表），`storage.py` 封装CRUD（接收`sqlite3.Connection`，不持有全局连接）+ 通用分页`query_paginated()` + 重载信号方法。`collector.py` 主/备源容灾切换（连续失败3次切备用源，状态记入`data_source_status`表）。

**配置管理** (`config_manager.py`)：`CONFIG_META`定义所有配置项元数据（label/description/value_type/default），`STRATEGY_ATTR_MAP`和`STRATEGY_SUB_OBJ_MAP`映射配置键到策略实例属性。启动时`init_from_yaml()`从config.yaml写入`config_kv`表（仅DB为空时执行，幂等）。看板修改配置后插入`config_reload_signal`信号，调度器每30秒轮询检测并`setattr()`热更新策略实例。

**调度层** (`scheduler/`)：`calendar.py` 内存中维护节假日集合，从SQLite加载。`scheduler.py` 包装APScheduler，所有job自动判断交易日（非交易日跳过）。支持`remove_job()`/`modify_interval_job()`/`add_config_poll_job()`。

**策略层** (`strategies/`)：`base.py` 定义抽象基类。四个策略独立实现。LOF溢价监控拆为子包：`premium.py`(计算) → `filter.py`(过滤) → `signal.py`(防抖信号)。

**通知层** (`notify/`)：`NotificationManager`统一分发，支持桌面(plyer)/微信(Server酱)/钉钉(Webhook)三通道。`dual_channel_events`配置哪些事件双通道推送。

**看板** (`dashboard/`)：Flask `create_app()` 工厂函数，依赖注入storage和config_manager。API模式返回分页JSON，前端Petite-Vue SPA单页应用（3个标签页：状态总览/业务数据/配置管理）。Petite-Vue生命周期钩子用`@vue:mounted`（不是`@mounted`）。Jinja2模板用`{% raw %}...{% endraw %}`避免与Petite-Vue的`{{ }}`冲突。Bool配置值前后端统一存"0"/"1"。

**交易层** (`trader/`)：`executor.py` 包装xtquant，`execute_lof_arbitrage()`强制先卖后买顺序保护。`risk.py` 独立的风控检查器。**尚未接入main.py**，需miniQMT开通后集成。

## Key Design Decisions

- **IOPV精度**：主源用东方财富/集思录实时IOPV；回退到估算时阈值自动从2%提升到3%（`PremiumCalculator.get_threshold("estimated")`）
- **配债保守估值**：安全垫计算使用近3月同评级转债平均开盘溢价率×0.8保守系数（`BondAllocationStrategy._conservative_factor`）
- **执行顺序保护**：LOF套利必须先确认卖出成交回报再发起申购，杜绝裸卖空（`TradeExecutor.execute_lof_arbitrage`）
- **打新违约保护**：连续违约达2次自动暂停打新（`BondIpoStrategy.should_suspend`）
- **热加载信号机制**：Flask写入`config_reload_signal`表，调度器轮询检测后`setattr()`更新策略实例，无需重启
- **配置幂等初始化**：`init_from_yaml()`仅DB为空时执行，保留用户在看板中的修改

## Config

`config.yaml` 必须包含 `strategies` 和 `notify` 两个顶层段。关键配置项见 `config_loader.py` 的校验逻辑和 `config.yaml` 的注释。通知密钥（serverchan_key、webhook）通过配置文件管理，不要硬编码。配置已迁移到DB（`config_kv`表），看板可CRUD管理，热加载到策略实例。

## Testing

测试使用 `:memory:` SQLite + `unittest.mock`。无 `conftest.py`，每个测试模块自行创建存储实例。`test_dashboard_api.py`使用pytest fixture创建Flask test client。144个测试用例覆盖所有已实现模块。

## Implementation Gaps

- `BondAllocationStrategy.execute()` 是stub，只log
- `TradeExecutor` 和 `RiskChecker` 未接入 `main.py`
- 数据采集备用源为空实现
