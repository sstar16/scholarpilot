---
source_id: medrxiv
display_name: medRxiv
category: literature
language: en
query_format: plain
min_terms: 3
max_terms: 4
enabled_by_default: true
notes_zh: "医学预印本，API 仅日期范围，关键词用于本地过滤"
version: 3
---

# medRxiv 检索规则

## API 事实（硬约束）

- **API 本身不支持关键词搜索**，同 bioRxiv 机制
- Adapter 拿到全量后做本地过滤

## 适合主题

- 医学预印本（临床前 + 临床研究的最新工作）
- 流行病学、临床试验、公共卫生
- **不适合**：基础生物学（去 bioRxiv）

## 关键词生成规则

**推荐**：3-4 个英文医学术语
**避免**：
- 过于宽泛的词（增加本地过滤噪声）
- 中文

## 示例

| 研究主题 | 推荐 query |
|---|---|
| 锂电池摄入中毒 | `lithium battery ingestion emergency pediatric` |
| 新冠长期症状 | `COVID long hauler chronic symptoms` |
