---
source_id: openalex
display_name: OpenAlex
category: literature
language: en
query_format: boolean_bucket
min_terms: 3
max_terms: 12
max_phrases: 1
enabled_by_default: true
notes_zh: "全领域学术库，布尔桶同义词扩展（AND/OR 被当词但扩展召回），最多 1 处短语引号"
version: 6
---

# OpenAlex 检索规则

## API 事实（2026-04-25 实测更新）

- Elasticsearch 后端，覆盖 2 亿+ 篇学术文献
- **实测确认**：
  - plain 3 词 `cigarette capsule forming` → 12,930 条
  - 布尔桶 `(cigarette OR tobacco OR cigar) AND (capsule OR microcapsule) AND (forming OR molding) AND (device OR system)` → **20,746 条（召回 +60%）**
  - 同义词扩展 = 多个词进入 ES multi-match，召回翻倍
  - `AND/OR/NOT` 字符可能被 ES 当作普通关键词（旧测试有相同数据），但**布尔桶整体召回仍显著提升**——关键在于同义词扩展
  - `"quoted phrase"` 双引号短语**有效**（过去测 baseline 117938 → 短语 11812，精度 10×）
- **字段过滤**走 `filter=` 参数（如 `filter=publication_year:2023`, `filter=language:en`），不写进 `search=`
- 3-8 词最佳（桶+同义词允许稍多），超过 10 词会显著稀释 relevance

## 适合主题

全领域综合学术文献：生物、化学、物理、医学、计算机、材料、经济、社会科学等。**全局必选源**。

## 三层降级的关键词生成规则

### complex 层（精度 + 召回）
- **3-4 个同义词桶**，每桶 2-3 个同义词，布尔桶风格
- 可加 **1 个**关键短语引号（多了会过苛）
- 示例：
  - `(tobacco OR cigarette OR cigar) AND (capsule OR microcapsule) AND (forming OR molding OR dropping)`
  - `("lithium iron phosphate" OR LFP) AND (cathode OR electrode) AND (coating OR surface) AND (thermal OR stability)`
  - `(transformer OR attention) AND (inference OR decoding) AND (acceleration OR quantization)`

### medium 层
- **2 个同义词桶**，每桶 2 个同义词，无短语引号
- 示例：`(tobacco OR cigarette) AND (capsule OR microcapsule)`

### simple 层（兜底）
- 2-3 个最核心的术语，纯空格（无布尔无引号）
- 示例：`tobacco capsule`

## 禁止

- 超过 1 个 `"phrase"` 引号（严格 phrase AND 基本 0 命中）
- 通用词：research, study, analysis, method, approach, system（单独出现）
- 超过 4 个桶或 10 词以上（relevance 稀释）
- 在 `search` 里写 `filter=...`（应该交给 adapter）

## 示例对照

| 研究主题 | ✅ complex（布尔桶） | ✅ medium | ✅ simple |
|---|---|---|---|
| 烟草爆珠滴制 | `(tobacco OR cigarette) AND (capsule OR microcapsule) AND (forming OR molding OR dropping)` | `(tobacco OR cigarette) AND capsule` | `tobacco capsule` |
| 锂电池正极材料 | `("lithium iron phosphate" OR LFP) AND (cathode OR electrode) AND (coating OR surface)` | `(lithium OR LFP) AND cathode` | `LFP cathode` |
| CRISPR 基因治疗 | `(CRISPR OR "gene editing") AND (cancer OR tumor OR malignancy) AND (therapy OR treatment)` | `(CRISPR OR gene) AND cancer` | `CRISPR therapy` |
