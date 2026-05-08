---
source_id: epo_ops
display_name: EPO OPS (欧洲专利)
category: patents
language: en
query_format: plain
min_terms: 2
max_terms: 3
enabled_by_default: true
notes_zh: "欧洲专利，2-3 关键词（adapter 自动转 CQL ti/ab 字段）"
version: 3
---

# EPO OPS 检索规则

## API 事实（硬约束）

- 欧洲专利局官方 API
- **Adapter 会自动把关键词转成 CQL `ti/ab` 字段查询**（不需要你写 CQL 语法）
- **不能**有连字符（`-`），会让 CQL 解析报错
- **不能**用 CQL 原生语法（`ti=`, `ab=`），adapter 会自动加
- 最多 2-3 个关键词（过多导致结果稀释）

## 适合主题

- 欧洲专利（EP）、WIPO 国际申请（WO）
- 工程、机械、化学、材料、生物技术的欧洲专利

## 关键词生成规则

**必须**：2-3 个英文专利术语
**禁止**：
- 连字符（`high-entropy` 必须写成 `high entropy`）
- CQL 语法（写纯词，adapter 会加字段限定）
- 中文

## 示例

| 研究主题 | ✅ 正确 | ❌ 错误 |
|---|---|---|
| 锂电池包装 | `lithium battery packaging` | `lithium-ion packaging` |
| 高熵合金 | `high entropy alloy` | `high-entropy alloy` |
| 氢燃料电池 | `hydrogen fuel cell` | `ti="hydrogen fuel cell"` |
