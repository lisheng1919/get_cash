# 看板增强设计：分页搜索 + 配置管理

> 日期：2026-05-01
> 状态：已确认

## 概述

对现有看板进行轻量重构，实现两个核心功能：所有表格区域的分页与条件搜索、配置项从config.yaml迁移到看板CRUD管理。

## 技术方案

**Flask API后端 + Petite-Vue SPA前端**，替代现有Jinja2模板渲染模式。

选择理由：配置管理表单、分页搜索、热加载均为交互密集型功能，纯JS手写维护困难。Petite-Vue约6KB无构建工具，适合轻量级改造。

## 一、整体架构

```
前端 SPA (Petite-Vue)          Flask API 后端              SQLite
┌──────────────────┐      ┌────────────────────┐      ┌──────────────┐
│ 标签1：状态总览   │ ⇄    │ 数据查询API(分页)   │ →    │ 原有业务表    │
│ 标签2：业务数据   │      │ 配置管理API(CRUD)   │      │              │
│ 标签3：系统配置   │      │ 状态API / 静默API   │      │ config_kv NEW│
└──────────────────┘      └────────────────────┘      └──────────────┘
```

### 核心改动

1. **前端**：Jinja2模板 → 单页HTML + Petite-Vue，所有数据通过API获取
2. **后端**：业务数据路由改为分页API，新增配置CRUD API
3. **存储**：新增 config_kv 表，启动时从 config.yaml 初始化，后续看板修改写DB
4. **热加载**：配置修改后，Flask通过ConfigManager回调更新策略参数

## 二、分页与搜索

### 统一分页API规范

**请求参数**（所有数据API统一）：
```
?page=1&page_size=20&search=关键词&sort_by=字段&sort_order=desc
```

**响应格式**：
```json
{
  "items": [...],
  "total": 156,
  "page": 1,
  "page_size": 20,
  "total_pages": 8
}
```

### 各表格搜索条件

| 数据区域 | 搜索字段 | 排序字段 | 默认排序 |
|---------|---------|---------|---------|
| LOF溢价历史 | 基金代码、基金名称 | 记录时间、溢价率 | 时间倒序 |
| 交易信号 | 基金代码、信号类型 | 信号时间 | 时间倒序 |
| 可转债打新 | 债券代码、债券名称 | 申购日期 | 日期倒序 |
| 配债监控 | 股票代码、股票名称 | 股权登记日 | 登记日倒序 |
| 逆回购 | 操作日期 | 操作日期 | 日期倒序 |
| 日汇总 | 汇总日期 | 汇总日期 | 日期倒序 |
| 告警事件流 | 级别(ERROR/WARN/INFO)、来源、关键词 | 时间 | 时间倒序 |
| 通知发送记录 | 渠道、事件类型、状态 | 时间 | 时间倒序 |
| 已静默基金 | 基金代码、基金名称 | 到期时间 | 到期时间正序 |

### API端点改造

- 现有 `GET /` 不再服务端渲染数据，改为仅返回SPA页面
- 业务数据拆为独立API：`GET /api/data/lof_premium`、`GET /api/data/trade_signal` 等
- `GET /api/status` 扩展分页参数，告警和通知记录改为分页返回

### 分页控件

搜索框 + 每页条数选择(10/20/50) + 页码导航，统一组件复用。

## 三、配置管理

### config_kv 表结构

| 字段 | 类型 | 说明 |
|-----|------|------|
| category | VARCHAR NOT NULL | 分类：strategy / notify / risk / system，默认'' |
| section | VARCHAR NOT NULL | 子段：bond_ipo / lof_premium / desktop / ...，默认'' |
| key | VARCHAR NOT NULL | 配置键名：enabled / premium_threshold / ...，默认'' |
| value | TEXT NOT NULL | 值（JSON序列化，统一存TEXT），默认'' |
| value_type | VARCHAR NOT NULL | 类型标记：bool / int / float / string，默认'string' |
| label | VARCHAR NOT NULL | 中文标签：溢价率阈值 / 自动申购 / ...，默认'' |
| description | VARCHAR NOT NULL | 说明文案，默认'' |
| create_time | DATETIME NOT NULL | 创建时间，默认CURRENT_TIMESTAMP |
| update_time | DATETIME NOT NULL | 最后修改时间，默认CURRENT_TIMESTAMP |

主键：(category, section, key)。启动时从config.yaml初始化（仅DB为空时）。

### 配置API

| 端点 | 方法 | 说明 |
|-----|------|------|
| `/api/config?category=strategy` | GET | 按分类查询配置项列表 |
| `/api/config` | PUT | 批量更新 `{items: [{category, section, key, value}]}`，更新后自动触发reload |
| `/api/config/reload` | POST | 手动触发热加载（用于异常恢复场景） |

### 配置页UI

新增"系统配置"标签页，4个分组卡片：

1. **策略配置**：4个策略的启停开关 + 各策略参数（如溢价阈值、最大违约次数等）
2. **通知配置**：微信/钉钉开关 + 密钥/webhook配置 + 双通道事件
3. **风控配置**：最大回撤、单日交易上限、硬止损等
4. **系统配置**：自检开关、心跳间隔、数据保留天数等

每个分组内按section折叠展示，checkbox控制布尔值，number输入框控制数值，分组保存按钮。

## 四、热加载机制

### 流程

```
用户修改配置 → PUT /api/config → 写入config_kv表 + 插入config_reload_signal
→ 调度器轮询检测到未处理信号 → ConfigManager.reload()
→ 从SQLite读取最新配置 → setattr更新策略实例属性 → 下次执行自动使用新参数
```

Flask和APScheduler运行在独立进程中，通过SQLite的config_reload_signal表实现跨进程通信：Flask写入配置变更信号，调度器定期轮询检测并重载。

### ConfigManager 核心类

```python
class ConfigManager:
    def __init__(self, storage, scheduler, config_dict):
        """启动时：config.yaml → config_kv表，存引用到策略实例和调度器"""
        self._storage = storage
        self._scheduler = scheduler  # StrategyScheduler实例，策略启停时操作
        self._strategies = {}  # {name: strategy_instance}

    def register_strategy(self, name, strategy):
        """注册策略实例，热加载时更新其属性"""

    def reload(self):
        """从SQLite读取最新配置，逐策略更新属性"""
        # 1. 读 config_kv 表
        # 2. 按 section 分组
        # 3. 遍历策略实例，setattr 更新参数
        # 4. 特殊处理：策略启停(增删调度job)

    def get_config(self, category=None):
        """查询配置项，供API使用"""

    def update_config(self, items):
        """批量更新配置项，写入DB后自动触发reload()"""

    def init_from_yaml(self, config_dict):
        """首次启动：yaml → config_kv表（仅DB为空时执行）"""
```

### 策略启停热加载

- **启用策略**：向调度器添加对应job（若不存在）
- **禁用策略**：从调度器移除对应job（不删除策略实例）
- **轮询间隔变更**（如 lof_premium.poll_interval）：移除旧job并重新添加

### main.py 集成变更

1. 创建 ConfigManager 实例，传入 storage、scheduler 和 config_dict
2. 每个策略创建后，调用 `config_manager.register_strategy(name, strategy)`
3. 将 ConfigManager 注入 Flask app，API端点可直接调用
4. 启动时 `config_manager.init_from_yaml(config_dict)`（仅首次）

## 五、前端重构要点

### 技术选型

- **Petite-Vue**：Vue官方轻量版，约6KB，本地引入（`dashboard/static/petite-vue.js`），无需构建工具，支持离线运行
- 保留现有CSS样式体系，组件化封装表格、分页、表单等复用元素

### 页面结构

三个标签页，全部通过API获取数据：

1. **状态总览**：系统健康 / 数据源 / 通知 / 策略执行 / 告警(分页) / 通知记录(分页) / 已静默基金(分页)
2. **业务数据**：LOF溢价 / 交易信号 / 可转债打新 / 配债 / 逆回购 / 日汇总（均分页+搜索）
3. **系统配置**：策略 / 通知 / 风控 / 系统（CRUD表单）

### 组件复用

- `<x-data-table>`：通用数据表格组件，内置分页、搜索、排序
- `<x-config-section>`：配置分组卡片组件，自动根据value_type渲染控件

## 六、不做项

- 展示顺序调整（拖拽排序）：暂不做
- 中文化/国际化：暂不做
