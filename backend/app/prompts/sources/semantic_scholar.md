---
source_id: semantic_scholar
display_name: Semantic Scholar
category: literature
language: en
query_format: plain
min_terms: 3
max_terms: 5
max_phrases: 1
enabled_by_default: false
notes_zh: "AI 驱动的学术搜索引擎，提供引用分析，3-5 英文词"
version: 3
---

# Semantic Scholar 检索规则

## API 事实

- AI 驱动的学术文献搜索引擎（Allen AI 出品）
- 提供引用分析、influential citation 等高级指标
- 覆盖跨学科，尤其强在 CS/工程/生物医学
- 语义检索能力比关键词精确匹配更好
- **注意**：API 有时 429 限流，默认禁用，需手动启用

## 适合主题

- 跨学科综合检索（OpenAlex 的补充）
- 需要引用分析的场景（找经典文献、找被引最多的方法论）
- CS / AI / ML / NLP 顶会论文
- 生物信息学
- 任何主题的"高引用"筛选

## 关键词生成规则

**必须**：3-5 个英文专业术语
**推荐**：
- 语义搜索友好，不一定非要精确关键词，领域描述性词也行
- 可用 1 个短语引号强调核心概念
- 避免 generic 词

**禁止**：
- 超过 1 个 phrase 引号
- 中文

## 示例

| 研究主题 | 推荐 query |
|---|---|
| Transformer 预训练 | `transformer pretraining language model` |
| 锂电池正极 | `"lithium iron phosphate" cathode battery` |
| CRISPR 碱基编辑 | `CRISPR base editing efficiency off-target` |
