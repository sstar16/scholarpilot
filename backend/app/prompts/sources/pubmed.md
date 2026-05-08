---
source_id: pubmed
display_name: PubMed
category: literature
language: en
query_format: plain
min_terms: 3
max_terms: 5
max_phrases: 0
enabled_by_default: false
notes_zh: "美国国家医学图书馆生物医学库，3-5 英文词，MeSH 同义词自动扩展"
version: 3
---

# PubMed 检索规则

## API 事实

- 美国国家医学图书馆的生物医学文献数据库
- **MeSH 同义词自动扩展**（搜 "cancer" 自动覆盖 "neoplasm"、"tumor"、"malignancy"）
- 默认多词 AND
- 引用数据完整
- 2026-04-22 实测：阿里云 ECS 出境可直连，已从 DISABLED_SOURCES 移除

## 适合主题

- **生物医学**（首选）：病理、药理、临床、基因、蛋白、分子机制
- 公共卫生、流行病学
- 营养学、食品安全
- 相关交叉学科：农学、兽医、食品生物化学

## 不适合主题

- 纯 CS / 数学 / 物理 / 工程
- 材料科学（除非是生物材料）
- 专利类检索（这是文献库不是专利库）

## 关键词生成规则

**必须**：3-5 个英文医学/生物学术语，平铺用空格
**推荐**：
- 用标准医学英文术语（疾病用医学名称、化学物质用 IUPAC 名或通用名）
- 让 MeSH 自动扩展同义词，不要自己手写一堆同义词
- 不用双引号（phrase 会降低 MeSH 扩展效果）

**禁止**：
- 双引号短语（同 europe_pmc）
- 中文
- 通用学术套话（research/study/analysis）

## 示例

| 研究主题 | 推荐 query |
|---|---|
| CRISPR 癌症治疗 | `CRISPR cancer therapy gene editing` |
| 肠道菌群与炎症性肠病 | `gut microbiome inflammatory bowel disease` |
| 新冠疫苗效果 | `COVID vaccine efficacy booster` |
