# LOF溢价数据优化与数据源切换 Design Spec

## Why

当前LOF溢价历史存在两个问题：

1. **数据膨胀**：每60秒对每只活跃基金记录一条 `premium_history`，200只基金一天约产生28万行。同只基金的数据堆积在一起，看板翻页后大量重复记录，无法快速把握走势。`data_retention_days`/`data_aggregate_hours`/`db_vacuum_weekly` 三个配置项从未实现。

2. **数据源不全**：`akshare.fund_etf_category_sina(symbol="LOF基金")` 基于新浪分类，部分LOF基金（如华夏磐晟）不在新浪的"LOF基金"分类中，导致系统监控不到。

## What Changes

### 变更1：数据源切换（新浪 → 东方财富）

- `collector.py` 主源从 `fund_etf_category_sina` 改为复用 `fund_value_estimation_em(symbol="LOF")`，一次请求同时获取全量LOF基金列表+IOPV
- 新浪接口降级为备用源（原来的 `_fetch_lof_list_fallback` 从空实现改为调用新浪接口）
- `fetch_lof_fund_list` 返回格式不变，对调用方透明

### 变更2：溢价历史降采样

- 新增 `premium_hourly` 表存储每小时聚合数据
- 新增定时任务每小时聚合 `premium_history` → `premium_hourly`，聚合后删除已聚合的原始记录（超阈值记录保留）
- 新增定时任务每日清理超过 `data_retention_days`（默认90天）的历史数据，并按 `db_vacuum_weekly` 配置执行 VACUUM
- 看板LOF溢价历史默认显示分组汇总视图（按基金），点击展开超阈值明细

## Impact

- `data/collector.py` — 主源切换，备源实现
- `data/models.py` — 新增 `premium_hourly` 表DDL和索引
- `data/storage.py` — 新增聚合、清理、查询方法
- `main.py` — 注册聚合任务和清理任务
- `dashboard/app.py` — 新增汇总API，调整明细API
- `dashboard/templates/index.html` — LOF溢价历史改为分组视图+展开明细

---

## MODIFIED Requirements

### Requirement: LOF基金列表数据源

原主源 `akshare.fund_etf_category_sina(symbol="LOF基金")` 改为 `akshare.fund_value_estimation_em(symbol="LOF")`。该接口返回东方财富全量LOF估值数据，包含基金代码和名称列，覆盖更全。

#### Scenario: 主源正常

- **WHEN** 调用 `fetch_lof_fund_list`
- **THEN** 使用 `fund_value_estimation_em` 获取LOF基金列表（代码+名称），同时获取IOPV数据缓存供后续使用
- **AND** 返回格式与原来一致：`[{"code": "164906", "name": "...", "is_suspended": False, "daily_volume": 1234.5}]`

#### Scenario: 主源失败回退

- **WHEN** `fund_value_estimation_em` 连续失败达3次
- **THEN** 切换到备源 `fund_etf_category_sina(symbol="LOF基金")`
- **AND** 备源获取的列表仍按原格式返回

#### Scenario: 主源恢复

- **WHEN** 主源恢复成功
- **THEN** 自动切回主源（复用已有的容灾切换机制）

### Requirement: 溢价策略执行

策略的 `execute()` 方法逻辑不变，仍每轮对每只活跃基金写入 `premium_history`。降采样由独立定时任务完成，策略不感知。

---

## ADDED Requirements

### Requirement: premium_hourly 聚合表

系统应新增 `premium_hourly` 表存储每小时汇总数据。

#### 表结构

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| fund_code | TEXT | NOT NULL | 基金代码 |
| hour | TEXT | NOT NULL | 小时窗口，格式 "YYYY-MM-DD HH" |
| avg_premium | REAL | DEFAULT 0 | 该小时平均溢价率 |
| max_premium | REAL | DEFAULT 0 | 该小时最大溢价率 |
| min_premium | REAL | DEFAULT 0 | 该小时最小溢价率 |
| avg_price | REAL | DEFAULT 0 | 平均价格 |
| avg_iopv | REAL | DEFAULT 0 | 平均IOPV |
| sample_count | INT | DEFAULT 0 | 原始记录数 |
| threshold_count | INT | DEFAULT 0 | 超阈值次数 |
| create_time | TEXT | DEFAULT '' | 创建时间 |
| update_time | TEXT | DEFAULT '' | 更新时间 |

- 主键：`(fund_code, hour)`
- 索引：`idx_premium_hourly_hour` on `hour`（按时间范围查询）

### Requirement: 每小时溢价聚合任务

系统应在每小时的第5分钟执行聚合任务，将上一个小时的 `premium_history` 原始记录聚合到 `premium_hourly` 表。

#### Scenario: 正常聚合

- **WHEN** 聚合任务触发（如10:05触发，聚合09:00-09:59的数据）
- **THEN** 按 `fund_code, substr(timestamp,1,13)` 分组，计算 avg/max/min 溢价率、avg 价格/IOPV、采样次数、超阈值次数
- **AND** 写入/更新 `premium_hourly` 表（ON CONFLICT UPDATE）
- **AND** 删除已聚合的 `premium_history` 记录中**未超阈值**的记录（`ABS(premium_rate) < threshold`）
- **AND** 保留超阈值的 `premium_history` 记录不删除

#### Scenario: 无数据

- **WHEN** 上一小时无 `premium_history` 记录
- **THEN** 跳过，不写入 `premium_hourly`

### Requirement: 每日数据清理任务

系统应每日凌晨2:00执行数据清理，删除超过保留期的历史数据。

#### Scenario: 清理过期数据

- **WHEN** 清理任务触发
- **THEN** 读取 `data_retention_days` 配置（默认90天）
- **AND** 删除 `premium_hourly` 中 `hour < 当前日期 - retention_days` 的记录
- **AND** 删除 `premium_history` 中 `timestamp < 当前日期 - retention_days` 的记录
- **AND** 如果 `db_vacuum_weekly` 配置为 True 且本周尚未执行 VACUUM，则执行 `VACUUM`

### Requirement: LOF溢价分组汇总API

系统应新增API返回每只基金的溢价小时级汇总。

#### Scenario: 查询汇总

- **WHEN** `GET /api/data/lof_premium_summary?page=1&page_size=20`
- **THEN** 返回 `premium_hourly` 数据，按基金分组，每只基金显示最近一条汇总（含最新溢价率、采样次数、超阈值次数）
- **AND** 支持搜索（按基金代码/名称）
- **AND** 支持分页

#### Scenario: 查询某基金历史

- **WHEN** `GET /api/data/lof_premium_summary?fund_code=164906&days=7`
- **THEN** 返回指定基金最近N天的小时汇总列表，按时间倒序

### Requirement: LOF溢价明细API调整

原有 `/api/data/lof_premium` 调整为查询某基金的超阈值明细记录。

#### Scenario: 查询基金明细

- **WHEN** `GET /api/data/lof_premium?fund_code=164906`
- **THEN** 返回指定基金在 `premium_history` 中的超阈值记录（按时间倒序分页）

#### Scenario: 无基金代码参数

- **WHEN** `GET /api/data/lof_premium` 不带 `fund_code`
- **THEN** 返回最近100条超阈值记录（跨基金，按时间倒序）

### Requirement: 看板LOF溢价分组视图

前端LOF溢价历史标签页改为分组视图模式。

#### Scenario: 默认视图

- **WHEN** 用户打开LOF溢价历史
- **THEN** 显示基金分组列表，每行一只基金：基金代码、基金名称、最新溢价率、超阈值次数、最近更新时间
- **AND** 支持搜索和分页

#### Scenario: 展开明细

- **WHEN** 用户点击某基金行
- **THEN** 展开显示该基金的超阈值溢价明细记录（时间、价格、IOPV、溢价率、IOPV来源）
- **AND** 支持分页

#### Scenario: 查看历史趋势

- **WHEN** 用户点击"查看历史"按钮
- **THEN** 显示该基金最近7天的小时级汇总列表

---

## REMOVED Requirements

无。原有API和功能保持向后兼容。
