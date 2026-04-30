# 策略层补全设计文档

> 日期：2026-04-30
> 状态：已确认

## 背景

操作手册中标注6个未完成功能，本次聚焦策略层4项：
1. 节假日自动同步
2. IOPV数据获取
3. LOF溢价策略组装
4. 配债策略逻辑补全

方案：渐进式集成，按依赖链从底向上逐个接入，每步可独立测试。

---

## 1. 节假日自动同步

### 改动文件
- `scheduler/calendar.py` — 新增 `sync_from_akshare(storage)` 方法
- `main.py` — 启动时自动调用

### 设计

**`TradingCalendar.sync_from_akshare(storage)`**：
- 调用 `akshare.tool_trade_date_hist_sina()` 获取A股历史交易日列表
- 将每个交易日写入 `holiday_calendar` 表（`is_trading_day=True`）
- 非交易日推断：自然工作日（周一至周五）但不在交易日列表中的日期，标记 `is_trading_day=False`
- 节前交易日推断：如果某交易日之后紧接的非交易日 >=2天（长假），标记 `is_pre_holiday=True`
- 节假日名称推算：根据日期范围匹配（元旦1月、春节1-2月、清明4月、劳动节5月、端午6月、中秋9-10月、国庆10月）
- 增量同步：只拉取数据库中最后记录日期之后的新数据

**`main.py` 集成**：
- 在 `calendar.load_from_storage(storage)` 之后，检查 `holiday_calendar` 表是否为空
- 为空则调用 `calendar.sync_from_akshare(storage)` 自动同步

---

## 2. IOPV数据获取

### 改动文件
- `data/collector.py` — 新增 `fetch_lof_iopv(codes)` 方法

### 设计

**`DataCollector.fetch_lof_iopv(codes: List[str]) -> Dict[str, Dict]`**：
- 通过 `akshare.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")` 获取最新一天数据
- 提取收盘价作为IOPV近似值（LOF的IOPV本质就是基金净值）
- 返回格式：`{"fund_code": {"iopv": float, "iopv_source": "estimated"}}`
- 所有数据标记 `iopv_source="estimated"`，`PremiumCalculator.get_threshold("estimated")` 返回 `low_precision_threshold`（3%）
- 后续接入 xtquant 后可增加实时IOPV，`iopv_source` 变为 `"realtime"`，阈值自动降至2%

---

## 3. LOF溢价策略组装

### 改动文件
- 新建 `strategies/lof_premium/strategy.py` — `LofPremiumStrategy` 类
- `main.py` — 导入、实例化、注册、调度
- `config.yaml` — 增加 `auto_trade` 配置项

### 设计

**`LofPremiumStrategy(BaseStrategy)`**：
- `name = "lof_premium"`
- 构造函数：接收 `config, storage, notifier`，额外属性注入 `_collector`（与 BondIpoStrategy 同模式）
- 内部持有三个组件实例：`PremiumCalculator`、`LofFilter`、`SignalGenerator`
- 从 config 读取参数：`premium_threshold`、`low_precision_threshold`、`min_volume`、`confirm_count`、`cooldown_minutes`

**`execute()` 流程**：
1. `collector.fetch_lof_fund_list()` → 获取LOF基金列表
2. `LofFilter.filter_by_volume()` + `filter_by_suspension()` → 过滤
3. `collector.fetch_lof_iopv(codes)` → 获取IOPV
4. `collector.fetch_lof_realtime(codes)` → 获取市价
5. 对每只基金：`PremiumCalculator.calculate(price, iopv)` → 计算溢价率
6. `PremiumCalculator.get_threshold(iopv_source)` → 获取对应阈值
7. 溢价率超过阈值时：`SignalGenerator.check(fund_code, premium_rate)` → 判断信号
8. 信号生成后：
   - `storage.insert_premium_history()` → 记录溢价历史
   - `storage.insert_trade_signal()` → 记录交易信号
   - `notify()` → 推送通知
   - 如果 `auto_trade=True` 且 TradeExecutor 可用 → 调用交易执行（当前版本预留接口，不实际调用）

**`main.py` 集成**：
- 导入 `LofPremiumStrategy`
- 实例化并注入 `collector`
- 注册到 `StrategyScheduler`
- 用 `add_interval_job("lof_premium", poll_interval)` 添加间隔轮询（默认5秒）

**`config.yaml` 补充**：
```yaml
lof_premium:
  # ... 已有配置 ...
  auto_trade: false  # 是否自动交易，默认关闭
```

---

## 4. 配债策略逻辑补全

### 改动文件
- `strategies/bond_allocation.py` — 补全 `execute()` 方法
- `data/collector.py` — 新增 `fetch_bond_allocation_list()` 方法
- `main.py` — 给 BondAllocationStrategy 注入 collector

### 设计

**`DataCollector.fetch_bond_allocation_list() -> List[Dict]`**：
- 调用 `akshare.bond_zh_cov_new_em()` 获取可转债发行列表
- 结合 `akshare.stock_individual_info_em(symbol=stock_code)` 获取正股名称和价格
- 返回格式：`[{"code": "转债代码", "name": "转债名称", "subscribe_date": "申购日期", "stock_code": "正股代码", "stock_name": "正股名称", "stock_price": float, "content_weight": float}]`
- 含权量（content_weight）akshare 暂无此字段，使用默认估算值20%

**`BondAllocationStrategy.execute()` 补全**：
1. `collector.fetch_bond_allocation_list()` → 获取即将发行转债及正股信息
2. 筛选申购日期在未来 `notify_before_record_day` 天内的标的
3. `is_stock_excluded(name)` → 排除ST/退市股
4. `calc_safety_cushion(price, content_weight, avg_premium)` → 计算安全垫
   - `avg_premium` 使用固定默认值0.30（30%），后续可优化
5. 筛选安全垫 >= `min_safety_cushion` 的标的
6. `is_rush_warning(recent_rise_pct)` → 检查抢权预警
   - `recent_rise_pct` 暂用0（无法从akshare直接获取近期涨幅），后续可补充
7. `storage.upsert_bond_allocation()` → 入库
8. `notify()` → 推送通知

**`main.py` 集成**：
- 在创建 `bond_alloc` 后注入 collector：`bond_alloc._collector = collector`

---

## 依赖关系

```
节假日同步 (1) ──→ 被所有策略依赖（交易日判断）
IOPV获取 (2) ──→ 被LOF策略依赖
LOF策略组装 (3) ──→ 依赖 (1) + (2)
配债逻辑补全 (4) ──→ 依赖 (1)，独立于 (2)(3)
```

实现顺序：1 → 2 → 3 → 4（其中3和4可并行，但建议按顺序确保每步可测试）

---

## 不在本次范围内

- 交易执行层接入（需 miniQMT）
- 备用数据源实现
- 配置项 `position.*`、`risk.*` 的消费
- NotificationManager 双通道事件逻辑
