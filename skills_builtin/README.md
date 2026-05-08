# Skill 作者指南

> 受 [pi-skills](https://github.com/badlogic/pi-skills) / Claude Code Skills 启发：一个 skill = 一个带 YAML frontmatter 的 markdown 文件。
> 不写代码也能扩展 ScholarPilot 的研究能力。

---

## 这是什么

每一个 `*.md` 文件就是一个 **skill**（研究人格 / 输出风格）。系统启动时自动扫描这些目录：

| 优先级（高 → 低） | 路径 | 用途 |
|---|---|---|
| 1（最低）| `skills_builtin/` （此目录） | 项目内置示例，git tracked，所有部署都有 |
| 2 | `~/.scholarpilot/skills/` | **用户全局** — 你的私有 skill，跨项目共享 |
| 3（最高）| `<cwd>/.scholarpilot/skills/` | 项目级覆盖 — 当前部署专属 |

**同名时高优先级覆盖低优先级**。所以你可以在 `~/.scholarpilot/skills/literature-review.md` 写一个**覆盖**项目内置 `literature-review.md` 的版本，专属自己使用。

---

## 一个 skill 长什么样

```markdown
---
name: my-domain-expert
description: 半导体材料专家 - 关注晶格 / 缺陷 / 器件尺度跨层关联
triggers: [半导体, 晶格, 器件, 缺陷, semiconductor, lattice]
hook_points: [collab_respond, summary]
priority: 10
persona_role: system_prefix
---

# 角色

你是一名半导体材料研究员，擅长把单篇论文的实验现象 ...

# 输出要求

## 关键发现
- ...

## 跨尺度关联
- 这个工作在「材料 → 器件 → 系统」哪一环？...

## 风险信号
- 实验条件是否过于理想？...

# 风格约束
- 中文输出，保留英文术语
- 短平快，bullet 优先
```

---

## frontmatter 字段规范

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `name` | ✅ | string (kebab-case) | 全局唯一 ID。命名约束：`^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$`（小写字母数字+连字符） |
| `description` | ✅ | string | 一句话描述，会被 LLM 用来判断"这个 skill 适不适合当前问题" |
| `triggers` | ⬜ | string[] | 关键词列表。当用户消息含其中之一时，skill_recommender_hook 会推荐启用此 skill |
| `hook_points` | ⬜ | string[] | 在哪些场景注入。默认 `["collab_respond"]`。已知值：`collab_respond`（协作研究回答）/ `summary`（文献摘要） |
| `priority` | ⬜ | int (default 0) | 多个 skill 同时命中时按 priority desc 排序，第一名获胜 |
| `persona_role` | ⬜ | `system_prefix` \| `system_suffix` | 注入位置。`system_prefix` = 拼到 system prompt 最前面（强势人格）；`system_suffix` = 拼到末尾（轻度风格补充）。默认 `system_prefix` |

**body**（`---` 之后的全文）会被作为 markdown 文本拼到 LLM 的 system prompt 里，所以**像写给同事的指令一样写**：角色定位 → 要做什么 → 输出格式 → 风格约束。

---

## 写好一个 skill 的 6 条建议

1. **角色锚定要具体**：不要只写"你是研究员"，写"你是半导体器件研究员，服务对象是晶圆代工厂工艺工程师"。受众越具体，输出越精准。

2. **输出结构强约束**：列出每个 section 的标题和子要求（"关键发现" "跨尺度关联" "风险信号"），LLM 会按结构填，避免啰嗦的散文。

3. **明示禁忌**：写一行"不要写 generic 的'本研究意义重大'套话"比让 LLM 自己拿捏更可靠。

4. **数据缺失的处理方案**：明示"文献没说就标 `?` 或 `(文献未提)`，**不准编**"——这是常见 LLM 失控点。

5. **区分事实 vs 判断**：让 LLM 在每条结论后标 `(事实)` / `(我的推断)`，方便你审查。

6. **保留语言**：中文项目里用中文，但**论文标题、术语、模型名保留英文**。

---

## 加好 skill 后做什么

skill 加在 `~/.scholarpilot/skills/foo.md` 后：

1. **重启 backend**：`docker compose restart backend`（Skill 注册发生在 lifespan startup）
2. **看启动日志**确认加载：
   ```
   [Harness] Markdown Skills: N loaded from .md files
   ```
3. **测试触发**：在对话里发一句包含 trigger 关键词的消息，看 skill_recommender_hook 是否推荐。

---

## 调试技巧

| 现象 | 可能原因 | 排查 |
|---|---|---|
| skill 没加载 | name 不是 kebab-case / body 为空 / frontmatter 语法错 | 看 backend 启动日志 `[markdown_loader] xxx 跳过` |
| 加载但不触发 | triggers 没命中 / priority 太低被别的 skill 抢 | 在系统设置 → DevView 里看 hook 触发记录 |
| 触发但 LLM 没按指令输出 | system prompt 被覆盖 / persona_role 写错 | 用 `system_prefix` 强势注入；body 顶部加"严格按以下格式输出"|

---

## 现成的 3 个内置 skill 可以参考

| 文件 | 适用场景 |
|---|---|
| `competitive-analysis.md` | 产业研究 / 早期投资 / 技术选型 — 给"判断"不给"summary" |
| `frontier-tracker.md` | 定期跟踪某细分方向 — "这个月相对上个月有什么真新东西" |
| `literature-review.md` | 学术综述写作 — 高强度结构化、严格区分事实和推断 |

复制其中一个改改字段、改改 body，就是你自己的 skill。
