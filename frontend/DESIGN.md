# ScholarPilot · Design System "Ink & Signal"

> 单一事实源。所有 UI 生成 / 改动必须先读此文件，再查 `src/assets/design-system.css`。
> 灵感来源：**中国水墨 × 科学仪表盘**。深灰墨色做主体，少量信号色做强调，任何时候不超过 2 个饱和色共存。

---

## 1 · 设计原则（Hard Rules）

| # | 原则 | 不能做 |
|---|---|---|
| 1 | **信息密度优先** | 不要用超大间距／海报级 hero 填屏幕。学者一屏装得下越多真·信息越好。 |
| 2 | **静默美学** | 除"检索中 / LLM 思考中"外不要动（别出现常态 pulse / shimmer 背景） |
| 3 | **一眼能找到下一步** | 每个 view 只有一个主 CTA，primary 色填充；次要 action 默认 plain / text |
| 4 | **富消息是会话的基石** | 所有异步流程（检索/协作/导入）必须以 `rich-msg` 气泡存在，不是 toast |
| 5 | **中文为主，英文技术词保留原文** | 不要把 "DOI" 翻成"数字对象标识符"、不要把 "PubMed" 音译 |
| 6 | **避免彩虹** | 一个界面同时出现 teal + amber + coral + blue = 禁止。最多主色 + 1 状态色 |
| 7 | **反馈即时** | 任何 >200ms 的操作必须立即出现 loading 状态（按钮 loading / skeleton / pulse） |

---

## 2 · 色彩系统（严格锁定）

### Ink 墨色（主体文本 / 背景）
```
--ink-950: #0a0e14   /* 最深 · 代码 */
--ink-900: #111827   /* 正文标题 */
--ink-700: #243044
--ink-500: #475569   /* 次要文字 */
--ink-400: #64748b   /* 辅助文字 */
--ink-300: #94a3b8   /* 占位符 */
--ink-200: #cbd5e1
--ink-100: #e8edf3   /* 分隔线 */
--ink-50:  #f1f5f9   /* 卡片背景 */
```

### Signal 信号色（功能强调，**每个界面最多用 2 个**）
| 变量 | 值 | 语义 | 用法 |
|---|---|---|---|
| `--signal-teal` | `#0d9488` | 主 CTA · 数据正常 | "开始检索"/ "确认"按钮；活跃标签 |
| `--signal-amber` | `#d97706` | 等待 · 需关注 | "待确认"/ "等待反馈"；keyword_confirmation 边框 |
| `--signal-coral` | `#dc2626` | 错误 · 危险 | 失败/错误 tag；删除确认 |
| `--signal-blue` | `#2563eb` | 信息 · 链接 | 进行中进度条；文档 DOI 链接 |
| `--signal-emerald` | `#059669` | 成功完成 | 已完成 round 卡片；已就绪导入文档 |

### 纸面层
```
--paper:       #ffffff   /* chat 主背景 */
--paper-cool:  #f8fafc   /* app body */
--paper-warm:  #fefcf9   /* 文献卡 hover */
--paper-hover: #f1f5f9
```

### 禁用色
- 纯黑 `#000000`（用 `--ink-950`）
- 纯白文字在浅底（用 `--ink-900`）
- `magenta/pink/purple` 系除非标记特殊（如 AI 生成）

---

## 3 · 字体

```
--font-display: 'Noto Serif SC', 'Georgia', 'Songti SC', serif;   /* 大标题/空状态 */
--font-body:    'DM Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--font-mono:    'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
```

### 字号表

| 场景 | size | weight | line-height |
|---|---|---|---|
| App Hero / 空态 | 32px (display) | 500 | 1.3 |
| 页面主标题 | 20px | 600 | 1.4 |
| 卡片标题 | 15px | 600 | 1.45 |
| 正文 | 14px | 400 | 1.6 |
| 次要文本 | 13px | 400 | 1.5 |
| 标签 / 时间戳 | 11-12px | 500 | 1.4 |
| 代码 | 12-13px mono | 400 | 1.5 |

**禁止** 在卡片里混用 >3 个字号。

---

## 4 · 间距 · 圆角 · 阴影

```
--radius-sm: 6px     /* tag / input */
--radius-md: 10px    /* card */
--radius-lg: 14px    /* rich-msg */
--radius-xl: 20px    /* modal / large panel */
--radius-full: 100px /* pill button / badge */
```

**8px 节拍**：所有 padding/margin 必须是 4/8/12/16/20/24 的倍数。

**阴影**（默认卡片不加阴影，hover 才给 sm）：
```
--shadow-sm:  0 2px 8px rgba(0,0,0,0.05)       /* hover 卡片 */
--shadow-md:  0 4px 16px rgba(0,0,0,0.06)      /* 浮层 */
--shadow-lg:  0 8px 32px rgba(0,0,0,0.08)      /* modal */
--shadow-glow-teal: 0 0 20px rgba(13,148,136,0.15)  /* 只给主 CTA 聚焦 */
```

---

## 5 · 动画

```
--ease-out: cubic-bezier(0.22, 1, 0.36, 1)      /* 默认 */
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1) /* rich-msg 入场 */
--duration-fast: 150ms    /* hover 色变 */
--duration-normal: 250ms  /* 常规过渡 */
--duration-slow: 400ms    /* 折叠/展开 */
```

### 必用动画

| 场景 | animation | 规则 |
|---|---|---|
| 富消息入场 | `richEnter` (scale 0.96→1, translateY 10px→0, fade) | `.rich-msg` 根类自动带（不用手工加） |
| 助手消息入场 | `fadeUp` | ChatMessage 内置 |
| Loading 点 | `pulse-dot` | 只在明确"思考中"用 |
| 进度条 shimmer | `shimmer` | 搜索进行中用；完成后必须停 |
| 按钮按下反馈 | `transform: scale(0.97)` | `.el-button:active` 全局生效 |

### 禁用
- 任何循环 `rotation` 动画（转圈图标用 Element Plus 的 `is-loading`）
- 多于 3 个并发 shimmer / pulse 同屏
- 长度 >500ms 的入场动画

---

## 6 · 组件 Do / Don't

### Buttons

```vue
<!-- ✅ 主 CTA：最多 1 个 -->
<el-button type="primary">开始检索</el-button>

<!-- ✅ 次要：plain / text -->
<el-button>取消</el-button>
<el-button text>展开详情</el-button>

<!-- ❌ 不要多个同级 primary 按钮 -->
<el-button type="primary">保存</el-button>
<el-button type="primary">导出</el-button>  <!-- 选一个降级 -->

<!-- ❌ 不要用 warning/danger 做普通操作 -->
<el-button type="warning">确认</el-button>  <!-- 用 primary -->
```

### 富消息（Rich Message）气泡

每个 rich_type 对应一个组件，根元素必须带 `.rich-msg`：

```vue
<div class="rich-msg rich-msg--keyword is-done">
  <!-- is-done/is-collapsed/is-active 切换状态样式 -->
</div>
```

**状态色映射**：
- 待确认 / 需要用户交互 → `amber` 边框 + `#fefce8` 背景
- 进行中 → `blue` 边框 + `#eff6ff` 背景
- 已完成 → `emerald` 边框 + `#f0fdf4` 背景
- 失败 → `coral` 边框 + `#fef2f2` 背景

### Cards · 文献卡 DocumentCard

**必须能在 280px 宽的窄列里正常渲染**（协作模式的侧栏）。信息优先级：
1. 一句话摘要 (`one_line_summary`) —— 必显
2. 标题（中文优先，无则英文） —— 必显
3. 作者 + 年份 + 期刊 —— 次要
4. 4 桶分类按钮 / 桶标签 —— 操作

**Don't** 把 12+ 个 meta 字段都堆上（DOI / source / external_id / concept_tags / methods / results ... 放进"展开详情"）。

### Tags

```vue
<!-- size="small" 是 ScholarPilot 默认；default 只在主导航 -->
<el-tag size="small" type="success">已就绪</el-tag>
<el-tag size="small" type="warning">待确认</el-tag>
<el-tag size="small" type="info">{{ source }}</el-tag>
```

同一个 tag 群不要超过 5 个并排；多了必须换行 + 24px 以内高度。

### Inputs

- **所有输入框必须显示状态反馈**：聚焦（teal border）/ 错误（coral border + 下方 11px 红字）/ 禁用（ink-200 背景）
- `<textarea>` 必须设 `spellcheck="false"`（学术名词误报太多）
- 文件名 / DOI 输入用 `font-mono`

---

## 7 · Layout Patterns

### 三分屏（默认）

```
┌──────────┬──────────────────┬──────────┐
│ 左侧栏   │   ChatPanel      │ Workbench│
│ 项目树   │   (主对话)       │ (可折叠) │
│ 280px    │   flex: 1        │ 320px    │
└──────────┴──────────────────┴──────────┘
```

- 左栏背景 `--paper-cool`
- 中间背景 `--paper`
- 右栏背景 `--paper-cool`，`border-left: 1px solid var(--ink-100)`

### Mobile（<768px）

- 左侧栏 → 顶部 drawer
- 右侧 Workbench → 隐藏，改为底部 floating `AI 工作台` 按钮
- FunctionDock 横向 scroll 不换行

---

## 8 · 交互约定

| 场景 | 交互 | 反馈 |
|---|---|---|
| 点击主 CTA | 立即 loading + disabled | 成功后 toast ElMessage.success |
| 表单错误 | 输入框 border coral + 字段下方 11px 红字 | 不弹 modal |
| 破坏性操作（删除/取消） | 必须 ElMessageBox.confirm | 确认文案用动词："确定删除" 而非 "是" |
| Long-running（>3s）操作 | rich-msg 显示进度 | 不要只给一个 spinner |
| 异步失败 | rich-msg 变 coral + 重试按钮 | 不要用 ElMessage.error 一闪而过 |
| 折叠 / 展开 | 按钮带箭头 ↓ / ↑ | transition: 250ms ease-out |

---

## 9 · 国际化

- 默认中文（所有 UI 字串），英文学术术语保留原文（PubMed / DOI / arXiv / OpenAlex）
- Element Plus 必须 `app.use(ElementPlus, { locale: zhCn })`
- 日期：中文短格式 `3月15日 14:32`，不用 `2026-03-15T14:32:00`

---

## 10 · 文件路径速查

| 需要改 | 去哪 |
|---|---|
| 颜色 / 字体 / 间距变量 | `src/assets/design-system.css` |
| 富消息组件 | `src/components/conversation/rich/*.vue` |
| ChatPanel 主对话 | `src/components/conversation/ChatPanel.vue` |
| FunctionDock 功能入口 | `src/components/conversation/FunctionDock.vue` |
| 文献卡 | `src/components/search/DocumentCard.vue` |
| 关键词编辑 | `src/components/search/KeywordConfirmPanel.vue` |

---

## 11 · AI 生成 UI 的额外硬约束

> Claude / Codex / Gemini 为此项目写 Vue 组件时必须遵守。

- ✅ 用 CSS 变量 `var(--xxx)`，不要硬编码十六进制颜色（除了偶尔的 rgba 半透明）
- ✅ 每个新组件放进 `rich/` 或领域子目录，不要堆在 `conversation/` 根
- ✅ 新 rich_type 必须同步：后端 `rich_type` 常量 + ChatPanel dispatch + 新组件带 `.rich-msg` 根类
- ❌ 不要引入新的 UI 库（antd / vuetify / naive-ui）—— 锁定 Element Plus
- ❌ 不要写内联 `style="..."` 超过 2 个属性 —— 用 `<style scoped>`
- ❌ 不要用 emoji 做视觉主体（只作辅助 icon）；主图标用 `@element-plus/icons-vue`
- ❌ 不要把 Element Plus 的 type="success/warning/danger" 当色板随便用 —— 只在语义匹配时用

---

_锁定时间：2026-04-18_
_修订此文件需在 commit message 标注 `[DESIGN]` 前缀。_
