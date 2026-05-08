# Page Spec: Dashboard (`/dashboard`)

**Purpose:** 项目列表主页,用户登录后首先看到。

## Layout

- **Top hero** — 页面标题「研究项目」+ 副标「管理你的文献检索与情报追踪」+ 右侧「新建项目」CTA
- **Below hero** — 项目卡片 grid(响应式:移动 1 列 / 平板 2 列 / 桌面 3 列)
- **Empty state** — 用户没有任何项目时的精致排版(现在是空态 bland)
- **Loading state** — 3 张 skeleton cards

## Card Anatomy (required)

- Status ribbon (右上小 chip):`active` / `paused` / `awaiting_feedback`
- Title — Noto Serif SC,20–22px
- Description — 1–2 行,超出 `…` 截断
- Domain chips — 1–3 个领域标签,小号
- Footer:
  - Round indicator — 圆点(active/inactive)+ 文字「第 N 轮」
  - Created date — 右侧,低调

## Interaction

- Hover:subtle lift + shadow depth(不要过度,避免 flashy)
- Click:navigate to `/projects/:id`
- CTA 按钮:teal primary,`btn-tap:active` 时 scale(0.97)

## Constraints

- MUST use Ink & Signal palette
- 中文 labels everywhere
- No background gradients, no purple, no Inter
- Card 本身使用 `--paper` 或 `--paper-warm`,grid 背景用 `--paper-cool`

## Sample Data (用这个,不要编英文)

3 张示例卡片,填中文学术项目名:

1. **CRISPR-Cas9 脱靶效应机制研究**
   - 描述:综述近五年 CRISPR 脱靶预测与抑制策略,聚焦 high-fidelity Cas 变体。
   - 领域:生物医学 · 基因编辑
   - 状态:active,第 3 轮

2. **大语言模型中文推理能力评估**
   - 描述:对比主流中文 LLM 在数学推理、代码生成、多步规划上的表现。
   - 领域:计算机科学 · 自然语言处理
   - 状态:awaiting_feedback,第 2 轮

3. **铁电薄膜在神经形态计算中的应用**
   - 描述:HfO2 基铁电忆阻器的器件物理与阵列集成方案追踪。
   - 领域:材料科学 · 半导体
   - 状态:paused,第 1 轮

## Output

Interactive HTML prototype.
提供两个 frame toggle:
- **Populated** — 3 张卡片 grid
- **Empty** — 首次用户,精致的空态排版
