# Page Spec: ProjectView (`/projects/:id`)

**Purpose:** 单个研究项目的工作台。整个产品的**主要使用页**。

**现状:** 顶部 topbar + 主体对话区 + 可选右侧文献库抽屉 + 可切到 Library 视图。功能密集,视觉需要管理好层级。

## Top Bar (固定高度 52px 左右)

- 左侧:
  - 返回箭头
  - 项目标题(Noto Serif SC,可双击 inline 编辑)
  - 项目描述 / domains(小字号,次级颜色,可双击编辑)
- 右侧:
  - 「搜索设置」button(打开 dialog)
  - Status tag(pending / active / awaiting_feedback / completed)

## Main Body

三种模式互斥切换:

### 1. Chat workspace(默认)

- **左主区**:ChatPanel(消息流 + 富消息卡片 + 输入框)
  - 顶部小 header:icon + 「项目对话」+ 右侧 action buttons
    - 「文献库」toggle(打开右侧抽屉)
    - 「Library 视图」button(切换到 Library 模式)
- **右侧抽屉**(可开关):文献库 bucket 分类(4 桶)
- 协作态下:顶部额外一条 `CollaborationBanner`
- 右下角浮动:`NotebookDrawer` 项目笔记本触发器

### 2. Library view

全屏 `LibraryBrowser`,代替 chat 区。返回按钮回到 chat。

### 3. Collaboration mode

在 chat workspace 基础上:
- 顶部 `CollaborationBanner` 横幅(明显视觉区隔,提示"已进入协作模式")
- ChatPanel 内所有消息都基于选中的文献子集
- 必须有明显「退出协作」路径

## 视觉重点

- Top bar 和 main body 的**明确层级分隔**(细线 / 色块过渡)
- Chat 消息流的**阅读宽度防御**(不要让消息无限拉宽)
- 富消息卡片(KeywordConfirm / SearchProgress / RoundComplete / Collaboration*)视觉上要比普通文本气泡**更有分量**,但不能喧宾夺主
- 右侧文献库抽屉打开时不要遮挡 chat 输入框
- 状态 tag 的颜色必须跟 signal 系一致(pending→amber, active→teal, awaiting_feedback→amber-light, completed→emerald)

## Interaction

- 标题 / 描述:双击进入 inline 编辑,Enter 保存 / Esc 取消
- 文献库 toggle:button 有 active 态,带数字 badge(文献数量)
- 协作 banner:右侧「退出协作」清晰可点
- 模式切换:平滑过渡,不要 jarring

## 中文 labels

「项目对话」/「文献库」/「Library 视图」/「搜索设置」/「退出协作」
状态:「待开始」/「进行中」/「等待反馈」/「已完成」/「已暂停」

## Constraints

- 不要 sidebar nav(左侧已经没有 sidebar,保持现状)
- Chat panel 阅读最大宽度约 780px,居中
- 富消息卡片最大宽度与 chat 一致

## Output

Interactive HTML prototype.
三个 frame:
1. **Chat workspace 默认态** — 几条消息 + 一张 KeywordConfirm 富卡片
2. **Library view** — 列表 + 筛选
3. **Collaboration active** — 带 banner + 子集选中状态
