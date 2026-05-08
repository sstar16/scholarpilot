---
source_id: bigquery_patents
display_name: Google Patents (BigQuery) (中国专利)
category: patents
language: zh
query_format: chinese
min_terms: 2
max_terms: 4
enabled_by_default: true
notes_zh: "Google Patents 中国专利数据源，2-4 个精准中文关键词"
version: 3
---

# Google Patents 检索规则

## API 事实

- 通过 Google Patents API 检索中国专利（CN 开头的专利号）
- 支持中文关键词，空格分隔默认 AND
- **不推荐英文**（Google Patents 的中国专利 abstract 主要是中文）

## 适合主题

- 中国专利（发明、实用新型、外观设计）
- 中文研究项目**必选**
- 工业应用、工艺、配方、设备类主题

## 关键词生成规则

**必须**：2-4 个精准中文专利术语
**推荐**：
- 用工程/产品/技术视角的中文词
- 化学物质用中文名（磷酸铁锂、聚苯乙烯、香料缓释）
- 避免口语化

**禁止**：
- 英文（会显著降低召回率）
- 超过 4 个词
- 停用词（"的"、"和"、"研究"、"方法"）

## 示例

| 研究主题 | 推荐 query |
|---|---|
| 锂电池正极材料 | `磷酸铁锂 正极 制备` |
| 固态电池电解质 | `solid state electrolyte battery` |
| 柔性屏幕 | `柔性屏 折叠屏 显示` |
