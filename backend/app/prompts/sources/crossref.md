---
source_id: crossref
display_name: Crossref
category: literature
language: en
query_format: boolean_bucket
min_terms: 3
max_terms: 12
enabled_by_default: true
notes_zh: "跨学科元数据，布尔桶同义词扩展（召回实测 2.4×）"
version: 4
---

# Crossref 检索规则

## API 事实（2026-04-25 实测更新）

- 跨学科期刊论文元数据库（DOI 注册中心），强项：期刊引用数据、跨领域覆盖
- **实测推翻旧版 md 的"不支持布尔"说法**：
  - plain `cigarette capsule` → 79,328 条
  - 布尔桶 `(cigarette OR tobacco) AND capsule` → **186,811 条（召回 +135%，翻 2.4 倍）**
  - 机制：即便 API 不原生解析 AND/OR，同义词进入 `query` 参数会扩召回
- 年份过滤 `filter=from-pub-date:2020-01-01` 实测生效（79328 → 29207）
- **不支持**短语引号（会破坏匹配）

## 适合主题

- 综合学术文献（跨学科）
- 补充 OpenAlex 的次选项
- 查期刊/会议论文的引用数据

## 三层降级的关键词生成规则

### complex 层
- **3-4 个同义词桶**，布尔桶风格
- 示例：
  - `(tobacco OR cigarette) AND (capsule OR microcapsule) AND (forming OR molding OR dropping)`
  - `(lithium OR "iron phosphate") AND (cathode OR electrode) AND battery`

### medium 层
- **2 个同义词桶**
- 示例：`(tobacco OR cigarette) AND capsule`

### simple 层
- 2-3 个自然语言词
- 示例：`tobacco capsule`

## 禁止

- 短语引号 `"..."`（在 Crossref 上无精度提升，反而可能过滤掉）
- 通用词：research / study / analysis
- `NOT` 算子（Crossref 对 NOT 支持差，容易误杀）

## 示例

| 研究主题 | ✅ complex | ✅ medium |
|---|---|---|
| 烟草爆珠 | `(tobacco OR cigarette) AND (capsule OR microcapsule) AND (forming OR molding)` | `(tobacco OR cigarette) AND capsule` |
| 锂电池正极 | `(lithium OR LFP) AND (cathode OR electrode) AND battery` | `lithium cathode battery` |
| CRISPR 治疗 | `(CRISPR OR "gene editing") AND (cancer OR tumor) AND therapy` | `CRISPR cancer therapy` |
