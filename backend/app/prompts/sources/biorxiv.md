---
source_id: biorxiv
display_name: bioRxiv
category: literature
language: en
query_format: plain
min_terms: 3
max_terms: 4
enabled_by_default: true
notes_zh: "预印本，API 仅日期范围，关键词用于本地过滤"
version: 3
---

# bioRxiv 检索规则

## API 事实（硬约束）

- **API 本身不支持关键词搜索**，只能按日期范围拉全量
- Adapter 拿到全量后用关键词做**本地过滤**
- 因此关键词只影响过滤精度，不影响 API 调用

## 适合主题

- 生物学预印本（还未同行评审的最新工作）
- 细胞生物学、遗传学、神经科学、免疫学、进化生物学
- **不适合**：非生物学领域

## 关键词生成规则

**推荐**：3-4 个英文生物学术语
**避免**：
- 过于宽泛的词（本地过滤后仍有大量噪声）
- 中文（本地过滤是精确匹配，中文在英文摘要里不会命中）

## 示例

| 研究主题 | 推荐 query |
|---|---|
| CRISPR 基因编辑 | `CRISPR gene editing Cas9` |
| 神经退行性疾病 | `neurodegenerative Alzheimer tauopathy` |
