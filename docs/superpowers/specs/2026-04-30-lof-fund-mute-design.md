# LOF基金静默功能设计

> 日期: 2026-04-30
> 状态: 设计完成，待实施

## 背景

部分LOF基金虽有溢价但实际无法申购（暂停申购或限购金额太小无法套利），导致系统产生无效信号。需要提供一种机制让用户在看板上快速静默这些基金，设定静默天数后不再触发信号通知。

## 设计目标

- 看板上可一键静默基金，设定静默天数
- 静默期间该基金不产生信号、不发通知，但溢价历史照常记录
- 静默到期后自动恢复
- 可手动提前解除静默

## 数据层

### 扩展 lof_fund 表

新增字段：
- `muted_until TEXT NOT NULL DEFAULT ''` — 静默到期时间，空串表示不静默

`status` 字段使用 `muted` 值标记静默状态（现有值：`normal`、`suspended`）。

init_db 中加 ALTER TABLE 兼容迁移。

### Storage 层新增方法

- `mute_fund(code, muted_until)` — 设置 status='muted' + muted_until
- `unmute_fund(code)` — 恢复 status='normal' + 清空 muted_until
- `list_muted_funds()` — 查询所有 status='muted' 的基金

## 策略层

在 `LofPremiumStrategy.execute()` 中，信号生成前（`signal_gen.check()` 之前）增加检查：

- 如果该基金在 `active_funds` 中且其 `status='muted'` 且 `muted_until > 当前时间`，跳过信号（不写 trade_signal，不发通知）
- 如果 `muted_until <= 当前时间`（已过期），自动恢复为 `status='normal'`

溢价历史数据照常记录（`insert_premium_history`），仅跳过信号和通知。

实现方式：在 `strategy.py` 的 execute 循环中，premium_rate >= threshold 之后、`signal_gen.check()` 之前，查询 `lof_fund` 表的 status 和 muted_until 进行判断。

## 看板 + API

### POST /api/mute

请求体：`{"fund_code": "sz162719", "days": 7}`

逻辑：计算 muted_until = 当前日期 + days天，调用 `storage.mute_fund(code, muted_until)`

### POST /api/unmute

请求体：`{"fund_code": "sz162719"}`

逻辑：调用 `storage.unmute_fund(code)`

### 看板改造

- LOF溢价率监控表格增加"操作"列，显示"静默"按钮
- 点击后弹出输入框填写静默天数，确认后调用 `/api/mute`
- 状态总览页增加"已静默基金"区块，列出基金代码、名称、到期时间，可点"解除"
