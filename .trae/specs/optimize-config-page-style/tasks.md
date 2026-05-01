# Tasks

- [x] Task 1: 优化配置项 CSS 样式
  - [x] SubTask 1.1: 修改 `.config-grid` 网格布局，调整 minmax 为 260px
  - [x] SubTask 1.2: 修改 `.config-item` 为垂直分组布局（flex-direction: column），标签在上、输入框在下
  - [x] SubTask 1.3: 优化 `.config-item label` 样式，移除 min-width 限制，调整字号和颜色
  - [x] SubTask 1.4: 优化 `.config-item input` 样式，移除 max-width 限制，使输入框占满宽度
  - [x] SubTask 1.5: 移除 `.config-item .key-hint` 样式（不再需要独立元素）
  - [x] SubTask 1.6: 为 checkbox 类型配置项添加特殊布局样式，使其标签和 checkbox 水平排列
  - [x] SubTask 1.7: 增加输入框悬浮和聚焦的交互效果优化

- [x] Task 2: 修改配置项 HTML 模板
  - [x] SubTask 2.1: 为 text/number 输入框添加 `:placeholder="item.key"` 属性
  - [x] SubTask 2.2: 移除 `<span class="key-hint">{{ item.key }}</span>` 元素
  - [x] SubTask 2.3: 为配置项标签添加 `:title="item.description"` 属性
  - [x] SubTask 2.4: 为 checkbox 类型配置项调整布局结构（checkbox 与 label 水平排列）

# Task Dependencies
- Task 2 依赖 Task 1（CSS 样式先就位，HTML 模板修改后才能正确渲染）
