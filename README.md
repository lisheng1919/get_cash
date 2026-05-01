# 个人量化套利中枢 — 操作手册

## 一、当前已实现功能

| 策略 | 状态 | 说明 |
|------|------|------|
| **可转债打新** | ✅ 完整可用 | 09:30 自动检查当日可申购转债，推送通知，连续违约2次自动暂停 |
| **节假日逆回购** | ✅ 完整可用 | 14:30 自动检测节前交易日，计算可用资金，选择最优回购品种，推送提醒 |
| **可转债配债** | ✅ 完整可用 | 09:00 自动检查近期配债机会，安全垫计算，ST过滤，推送通知 |
| **LOF底仓套利** | ✅ 完整可用 | 间隔轮询检测溢价信号，通知+可选自动交易 |
| **交易执行** | ⚠️ 未接入 | `TradeExecutor`(先卖后买保护) 和 `RiskChecker`(风控) 已实现，未接入主流程，需 miniQMT |
| **看板** | ✅ 可用 | Flask 只读看板，展示5张表的最近数据 |
| **通知** | ✅ 桌面通知开箱即用 | 微信/钉钉需配置密钥 |

## 二、环境准备

```bash
# 1. 确保 Python 3.10+
python --version

# 2. 安装依赖
pip install -r requirements.txt

# 依赖包含：
#   akshare     — 行情数据源
#   apscheduler — 定时调度
#   plyer       — 桌面通知
#   pyyaml      — 配置解析
#   requests    — HTTP客户端（微信/钉钉通知）
#   flask       — 看板Web服务
```

## 三、必须配置项

编辑 `config.yaml`：

```yaml
# ===== 必须配置 =====
notify:
  desktop:
    enabled: true          # 桌面通知，开箱即用，建议保持开启
  wechat:
    enabled: false         # 如需微信推送，设为 true 并填入 key
    serverchan_key: ""     # Server酱 SendKey，从 https://sct.ftqq.com 获取
  dingtalk:
    enabled: false         # 如需钉钉推送，设为 true 并填入 webhook
    webhook: ""            # 钉钉机器人 Webhook URL

# ===== 按需调整 =====
reverse_repo:
  amount: 100000          # 逆回购金额（元），根据你的资金量调整
  min_rate: 3.0           # 最低年化收益率，低于此不推送
  reserve_ratio: 0.2      # 资金保留比例

bond_ipo:
  max_consecutive_miss: 2 # 连续未缴款次数上限，达到后暂停打新
```

### 通知通道配置说明

| 通道 | 配置方式 | 获取地址 |
|------|----------|----------|
| 桌面通知 | `enabled: true` 即可，无需额外配置 | — |
| 微信（Server酱） | 填入 `serverchan_key` | https://sct.ftqq.com |
| 钉钉 | 填入 `webhook` URL | 钉钉群 → 设置 → 智能群助手 → 添加机器人 → 自定义 |

## 四、运行方式

```bash
# 1. 启动主系统（阻塞式调度器，常驻运行）
python main.py

# 启动后会依次：
#   - 加载配置并校验
#   - 初始化 SQLite 数据库 (db/get_cash.db)
#   - 加载交易日历
#   - 运行自检（数据源连通性、数据库完整性、配置校验）
#   - 注册策略定时任务
#   - 启动心跳监控（每5分钟）
#   - 阻塞等待定时任务触发

# 自定义配置文件路径
python main.py path/to/config.yaml

# 2. 启动看板（另开终端）
python dashboard/app.py
# 访问 http://localhost:5000
# 展示：LOF套利信号、可转债打新、配债、逆回购记录、每日汇总

# 3. 运行测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_premium.py -v
```

## 五、定时任务时间表

| 策略 | 触发时间 | 条件 |
|------|----------|------|
| 可转债配债 | 每日 09:00 | 仅交易日 |
| 可转债打新 | 每日 09:30 | 仅交易日 |
| 逆回购 | 每日 14:30 | 仅交易日（节前才触发推送） |
| LOF溢价监控 | 每 5 秒（可配置） | 始终运行 |
| 心跳检查 | 每 5 分钟 | 始终运行 |
| 自检 | 启动时 | 始终运行 |

## 六、首次运行注意事项

1. **交易日历自动同步**：首次启动时 `holiday_calendar` 表为空，系统会自动从 akshare 拉取A股交易日历，后续启动增量同步
2. **数据源依赖 akshare**：打新和逆回购策略依赖 akshare 获取实时数据，网络不通会触发备用源切换（目前备用源为空实现）
3. **桌面通知**：Windows 下 plyer 桌面通知开箱即用，无需额外配置
4. **数据库自动创建**：`db/get_cash.db` 在首次启动时自动创建，含10张表

## 七、系统架构

```
Market APIs → DataCollector → Storage(SQLite) → StrategyScheduler → Strategy.execute() → Notifier/Trader
```

```
get_cash/
├── main.py                 # 主入口，启动调度器
├── config.yaml             # 配置文件
├── config_loader.py        # 配置加载与校验
├── requirements.txt        # Python 依赖
├── data/
│   ├── models.py           # 10张表DDL，init_db()建表
│   ├── storage.py          # CRUD操作（接收sqlite3.Connection）
│   └── collector.py        # 数据采集，主/备源容灾切换
├── scheduler/
│   ├── calendar.py         # 交易日历，节假日管理
│   └── scheduler.py        # APScheduler封装，交易日守卫
├── strategies/
│   ├── base.py             # 策略抽象基类
│   ├── bond_ipo.py         # 可转债打新
│   ├── bond_allocation.py  # 可转债配债
│   ├── reverse_repo.py     # 逆回购
│   └── lof_premium/        # LOF溢价套利子包
│       ├── strategy.py     # LOF溢价策略（组装三个子模块）
│       ├── premium.py      # 溢价计算
│       ├── filter.py       # 过滤（成交量、停牌）
│       └── signal.py       # 信号生成（确认+防抖）
├── notify/
│   ├── base.py             # 通知管理器，多通道分发
│   ├── desktop.py          # 桌面通知（plyer）
│   ├── wechat.py           # 微信通知（Server酱）
│   └── dingtalk.py         # 钉钉通知（Webhook）
├── trader/
│   ├── executor.py         # 交易执行（xtquant封装）
│   └── risk.py             # 风控检查器
├── dashboard/
│   ├── app.py              # Flask 看板
│   └── templates/
│       └── index.html      # 看板页面
├── tests/                  # 测试套件（86个用例）
└── docs/                   # 文档
```

## 八、未完成功能

| 项目 | 说明 |
|------|------|
| 交易执行接入 | `TradeExecutor` + `RiskChecker` 需接入 main.py，前置条件：开通 miniQMT |
| 实时IOPV获取 | 当前IOPV使用akshare日净值近似，接入xtquant后可获取实时IOPV，阈值将自动从3%降至2% |
| 备用数据源 | 所有 fallback 方法为空实现 |
| 配债含权量精确获取 | 当前使用默认估算值20%，需对接公告数据源 |
