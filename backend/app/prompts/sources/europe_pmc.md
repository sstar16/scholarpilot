---
source_id: europe_pmc
display_name: Europe PMC
category: literature
language: en
query_format: boolean_field
min_terms: 3
max_terms: 14
max_phrases: 2
enabled_by_default: true
notes_zh: "生物医学，complex 层可用 TITLE:/ABSTRACT: 字段 + 布尔桶 + 日期范围 + LANG"
version: 6
---

# Europe PMC 检索规则

## API 事实（2026-04-25 实测确认）

- PubMed 的欧洲镜像 + 预印本 + PMC 全文
- **MeSH 同义词自动扩展**（搜 "cancer" 自动扩展到 "neoplasms"、"malignancy"）
- 默认多词 AND（空格 = AND）
- **实测支持**：
  - 字段：`TITLE:"..."`、`ABSTRACT:"..."`、`AUTH:"..."`、`LANG:chi/eng/spa`
  - 布尔：`AND/OR/NOT`（原生支持）
  - 日期范围：`FIRST_PDATE:[YYYY-MM-DD TO YYYY-MM-DD]`
  - 短语：`"quoted phrase"`
- **2026-04-25 实测（主题 cigarette capsule）**：
  - plain → 5,462
  - 布尔桶 `(cigarette OR tobacco) AND (capsule OR microcapsule)` → **14,057（+157%）**
  - 字段精确 `TITLE:capsule AND ABSTRACT:tobacco` → 54（精度 100×）
  - `LANG:chi` 中文专属 → 3,069

## 适合主题

- 生物医学（病理、药理、临床、基因、蛋白）
- 农业、食品、兽医
- 生物学预印本
- **不适合**：纯 CS、数学、物理

## 三层降级的关键词生成规则

### complex 层（精度优先 —— 布尔桶 + 字段 + 日期）
- **3-4 个同义词桶** + 至少 1 处字段限定 或 日期范围
- 可叠：`TITLE:"..."` / `ABSTRACT:"..."` / `AUTH:"..."` / `FIRST_PDATE:[... TO ...]` / `LANG:chi`
- 示例：
  - `(TITLE:CRISPR OR TITLE:"gene editing") AND (cancer OR tumor OR malignancy) AND FIRST_PDATE:[2020-01-01 TO 2024-12-31]`
  - `(TITLE:"gut microbiome") AND (ABSTRACT:"inflammatory bowel disease" OR ABSTRACT:IBD)`
  - `("COVID-19 vaccine" OR "mRNA vaccine") AND (booster OR efficacy) AND FIRST_PDATE:[2022-01-01 TO 2024-12-31]`

### medium 层
- **2 个同义词桶**，不加字段限定
- 示例：`(CRISPR OR "gene editing") AND (cancer OR tumor)`

### simple 层
- 2-3 词纯空格
- 示例：`CRISPR cancer`

## 禁止

- 中文（除非明确走 `LANG:chi`）
- 通用学术套话（research / study / analysis）
- 超过 4 个桶或 10 词以上
- complex 层堆 ≥3 个严格字段（如 `TITLE:"a" AND TITLE:"b" AND ABSTRACT:"c" AND ABSTRACT:"d"` 过窄）
