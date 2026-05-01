# 配置管理页面样式优化 Spec

## Why
当前配置管理页面存在文字重叠问题，输入框后的英文标识（key-hint）作为独立元素占据额外空间，在窄屏或长标签场景下容易与输入框或标签重叠，导致展示不清晰、不美观。

## What Changes
- 将英文标识（key-hint）从输入框后的独立 `<span>` 改为输入框的 `placeholder` 属性，消除重叠源
- 优化 `.config-item` 布局，采用更清晰的垂直分组结构（标签在上、输入框在下），彻底避免水平空间不足导致的重叠
- 优化 `.config-grid` 网格布局，调整最小列宽和间距
- 美化输入框样式，增加悬浮和聚焦交互效果
- checkbox 类型配置项的布局单独优化，使其与文本/数字输入项视觉对齐
- 为配置项增加描述信息展示（使用 `item.description` 作为 tooltip）

## Impact
- Affected code: [index.html](file:///d:/Users/lisheng/IdeaProjects/get_cash/dashboard/templates/index.html) 中的 CSS 样式（第72-96行）和 HTML 模板（第388-436行）

## ADDED Requirements

### Requirement: 英文标识内嵌到输入框
系统应将配置项的英文标识（key）作为输入框的 `placeholder` 属性显示，而非作为独立的 `<span>` 元素显示在输入框后面。

#### Scenario: 文本/数字输入框显示 placeholder
- **WHEN** 配置项的输入类型为 text 或 number
- **THEN** 输入框应显示 `placeholder` 为该配置项的 key 值，输入框内无值时灰色显示 key

#### Scenario: checkbox 类型不显示 placeholder
- **WHEN** 配置项的输入类型为 checkbox
- **THEN** 不需要 placeholder，checkbox 后可保留小字 key-hint 或直接省略

### Requirement: 垂直分组布局
系统应将 `.config-item` 从水平排列（label + input + key-hint 一行）改为垂直分组排列（标签在上、输入框在下），彻底避免水平空间不足导致的文字重叠。

#### Scenario: 配置项垂直布局
- **WHEN** 用户查看配置管理页面
- **THEN** 每个配置项的中文标签在上方，输入框在下方，布局清晰不重叠

### Requirement: 配置项描述提示
系统应在配置项标签或输入框上提供 `title` 属性，鼠标悬浮时显示配置项的 `description` 描述信息。

#### Scenario: 鼠标悬浮显示描述
- **WHEN** 用户将鼠标悬浮在配置项标签上
- **THEN** 应显示该配置项的 description 描述信息

## MODIFIED Requirements

### Requirement: 配置网格布局
原 `.config-grid` 使用 `grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))`，现调整为 `repeat(auto-fill, minmax(260px, 1fr))`，适配垂直布局后更紧凑的列宽。

### Requirement: 配置项样式
原 `.config-item` 使用 `display: flex; align-items: center` 水平排列，现改为垂直分组布局，标签和输入框上下排列，间距合理。
