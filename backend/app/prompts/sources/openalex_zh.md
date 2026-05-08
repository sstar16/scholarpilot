---
source_id: openalex_zh
display_name: OpenAlex (中文/中国机构过滤)
category: literature
language: zh
query_format: dual
min_terms: 2
max_terms: 14
enabled_by_default: true
notes_zh: "双策略: 中文布尔桶(仅 display) + 英文布尔桶(实际查询 + country:cn 过滤)"
version: 4
---

# OpenAlex 中文/中国机构过滤规则

## API 事实（2026-04-25 实测重大调整）

- 基于 OpenAlex 做中文/中国作者文献过滤
- **`language:zh` 过滤基本无用**：实测主题 `cigarette capsule + language:zh` 仅 **2 条命中**（OpenAlex 中文原文极少，该字段几乎是空的）
- **新策略**：主要走 `country_code:cn`（中国机构发表的文献，含英文发表——这才是中国学者的主力）
- 保持 `dual` 格式 `中文|||英文`：
  - 中文部分：**仅用于前端 display 给用户看**，不参与实际 API 查询
  - 英文部分：实际发给 OpenAlex，配合 `filter=authorships.institutions.country_code:cn`

## 适合主题

- 中国作者的研究（中英文发表都能覆盖）
- 中文项目 **必选**
- 英文项目也可用来查中国团队成果

## 查询格式

严格：`<中文布尔桶>|||<英文布尔桶>`

## 三层降级的关键词生成规则

### complex 层
- 中文：2-3 个同义词桶（display 用）
- 英文：2-3 个同义词桶（真实查询）
- 示例：`(烟用 OR 卷烟) AND (爆珠 OR 胶囊)|||(tobacco OR cigarette) AND (capsule OR microcapsule)`

### medium 层
- 中文 1-2 桶；英文 1-2 桶
- 示例：`烟草 爆珠|||(tobacco OR cigarette) AND capsule`

### simple 层
- 中文 2 词；英文 2 词
- 示例：`爆珠|||tobacco capsule`

## 禁止

- 不要在中文部分写 `language:zh` filter（实测无效）
- 不要在任何部分写 `filter=...`（交给 adapter）
- 中英混合到同一部分（格式必须是 `中|||英`）

## 示例

| 研究主题 | complex |
|---|---|
| 烟草爆珠 | `(烟用 OR 卷烟) AND (爆珠 OR 胶囊)|||(tobacco OR cigarette) AND (capsule OR microcapsule)` |
| 锂电池正极 | `锂电池 正极 涂层|||(lithium OR LFP) AND (cathode OR electrode) AND coating` |
| 工业视觉缺陷 | `缺陷检测 深度学习|||(defect OR anomaly) AND (detection OR inspection) AND deep learning` |

**Return ONLY the dual-format string with `|||` separator, nothing else.**
