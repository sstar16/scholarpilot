# Page Spec: Login / Register (`/login`, `/register`)

**Purpose:** 登录 + 注册入口。当前用 Element Plus 默认样式,无品牌识别。

## 特殊情况

- **注册已关闭**(nginx 拦截),`/register` 保留但不暴露入口
- Login 是唯一对外可见入口

## Layout

两栏(桌面)/ 单栏(移动):

- **左栏(或移动页顶)**:品牌区
  - Logo / wordmark — Noto Serif SC 大字号
  - 一句 tagline:「全领域科研情报检索」
  - 辅助视觉:水墨风或科研仪器风的**克制**装饰(不要充满、不要插画过重)
- **右栏(或移动页底)**:Form
  - 邮箱 input
  - 密码 input
  - 「登录」primary button(teal,full width)
  - 错误提示区(空时不占位)
  - 无注册链接(已关闭)

## Interaction

- Email 实时 validate(失焦检查格式,非阻塞)
- 密码显示/隐藏 toggle(右侧小 icon)
- Enter 键提交
- 登录中:button 转 loading spinner,禁用 input
- 错误:coral color 文字提示,不要 shake 动画

## 中文 labels

- 「邮箱」/「密码」/「登录」/「登录中...」/「邮箱或密码错误」

## Constraints

- 不要 gradient background
- 不要"marketing 感" — 这是工具登录页,不是 landing
- 整页应该有**一个视觉锚点**(logo 或装饰)让人记住,不是纯白纯表单

## Output

Interactive HTML prototype.
同时提供 **error state**(登录失败)和 **loading state**(提交中)两个 frame。
