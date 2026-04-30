# LOF基金静默功能设计

> 日期: 2026-04-30
> 状态: 设计完成，待实施

## 背景

部分LOF基金虽有溢价但实际无法申购（暂停申购或限购金额太小无法套利），导致系统产生无效信号。需要提供自动+手动两种静默机制，减少无效信号干扰。

## 设计目标

- 系统启动时自动从akshare获取申购状态，将暂停申购和无套利空间的基金自动静默
- 用户可在看板上手动静默基金，设定静默天数
- 静默期间该基金不产生信号、不发通知，但溢价历史照常记录
- 静默到期后自动恢复
- 可手动提前解除静默

## 数据层

### 扩展 lof_fund 表

新增字段：
- `muted_until TEXT NOT NULL DEFAULT ''` — 静默到期时间，空串表示不静默
- `mute_reason TEXT NOT NULL DEFAULT ''` — 静默原因，如"暂停申购"、"套利利润不足(¥32)"、"手动静默"

`status` 字段使用 `muted` 值标记静默状态（现有值：`normal`、`suspended`）。

init_db 中加 ALTER TABLE 兼容迁移。

### Storage 层新增方法

- `mute_fund(code, muted_until, reason="")` — 设置 status='muted' + muted_until + mute_reason
- `unmute_fund(code)` — 恢复 status='normal' + 清空 muted_until 和 mute_reason
- `list_muted_funds()` — 查询所有 status='muted' 的基金

## 自动静默：DataCollector新增方法

### fetch_lof_purchase_status()

调用 `akshare.fund_purchase_em()` 获取全市场基金申购信息，筛选LOF基金，返回每只LOF的申购状态、限额和费率。

返回格式：`Dict[str, Dict]`，key为纯数字基金代码，value为：
```python
{
    "purchase_status": "正常申购" | "限大额" | "暂停申购",
    "purchase_limit": float,  # 申购累计限额（元），0表示无限制
    "purchase_fee_rate": float,  # 申购费率（小数，如0.0015表示0.15%）
}
```

### 套利利润计算

**核心公式**：
```
purchasable_amount = min(purchase_limit, available_capital)  # 实际可申购金额
gross_profit = purchasable_amount × premium_rate / 100       # 毛利润
purchase_fee = purchasable_amount × purchase_fee_rate        # 申购费用
sell_commission = purchasable_amount × sell_commission_rate  # 卖出佣金
fixed_costs = stamp_duty + transfer_fee + other              # 固定成本
net_profit = gross_profit - purchase_fee - sell_commission - fixed_costs
```

**参数说明**：
- `purchase_limit`：从 `fund_purchase_em()` 获取的申购限额，0表示无限制
- `available_capital`：用户可配置的可用资金，默认10万元
- `premium_rate`：当前溢价率（%）
- `purchase_fee_rate`：从 `fund_purchase_em()` 获取的申购费率
- `sell_commission_rate`：卖出佣金率，默认0.0003（万三）
- `fixed_costs`：印花税(卖出0.05%) + 过户费等，取固定值约1元

**实现位置**：在 `LofPremiumStrategy` 中新增静态方法 `calculate_arbitrage_profit()`。

### 自动静默逻辑

在 `main.py` 系统启动时，调用 `collector.fetch_lof_purchase_status()` 获取申购数据，按以下规则自动静默：

1. **暂停申购** → 自动静默30天（暂停申购通常不会短期恢复）
2. **限大额且套利利润不足** → 自动静默到当天结束
   - 调用 `calculate_arbitrage_profit(premium_rate=当前溢价率, ...)` 计算净利润
   - 若 `net_profit < min_profit_yuan`，自动静默，原因为"套利利润不足(¥{net_profit:.0f})"
   - 限额为0或正常申购的基金不受此规则影响
3. 已静默且 muted_until 尚未到期的基金，不重复静默（保留用户手动设置的静默）
4. 自动静默不覆盖手动静默（通过 mute_reason 区分：自动静默以"暂停申购"/"套利利润不足"开头，手动静默为"手动静默"）

**关于利润计算中的溢价率**：启动时获取的溢价率来自最近的 `premium_history` 记录。若某基金无历史记录，使用默认溢价率3.0%（略高于阈值，假设有信号时才需判断利润）。

### 配置项

在 `config.yaml` 的 `lof_premium` 段新增：
```yaml
lof_premium:
  auto_mute_enabled: true        # 是否启用自动静默
  min_profit_yuan: 200           # 最低套利利润（元），低于此值自动静默
  auto_mute_paused_days: 30      # 暂停申购自动静默天数
  available_capital: 100000      # 可用资金（元），用于计算套利利润
  sell_commission_rate: 0.0003   # 卖出佣金率（万三）
```

## 策略层

在 `LofPremiumStrategy.execute()` 中，信号生成前（`signal_gen.check()` 之前）增加检查：

- 如果该基金 `status='muted'` 且 `muted_until > 当前时间`，跳过信号（不写 trade_signal，不发通知）
- 如果 `muted_until <= 当前时间`（已过期），自动恢复为 `status='normal'`

溢价历史数据照常记录（`insert_premium_history`），仅跳过信号和通知。

实现方式：在 `strategy.py` 的 execute 循环中，premium_rate >= threshold 之后、`signal_gen.check()` 之前，查询 `lof_fund` 表的 status 和 muted_until 进行判断。

## 看板 + API

### POST /api/mute

请求体：`{"fund_code": "sz162719", "days": 7}`

逻辑：计算 muted_until = 当前日期 + days天，调用 `storage.mute_fund(code, muted_until, "手动静默")`

### POST /api/unmute

请求体：`{"fund_code": "sz162719"}`

逻辑：调用 `storage.unmute_fund(code)`

### GET /api/muted_funds

返回所有当前静默中的基金列表（代码、名称、原因、到期时间）。

### 看板改造

- LOF溢价率监控表格增加"操作"列，显示"静默"按钮
- 点击后弹出输入框填写静默天数，确认后调用 `/api/mute`
- 状态总览页增加"已静默基金"区块，列出基金代码、名称、原因、到期时间，可点"解除"
