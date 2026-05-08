---
source_id: local_kb
display_name: Local Knowledge Base
category: local
language: all
query_format: boolean_field
min_terms: 3
max_terms: 14
max_phrases: 2
enabled_by_default: false
notes_zh: "本地 OpenAlex 知识库 (DuckDB + SQLite FTS5)，支持布尔桶 + 字段 + 中英文"
version: 4
---

# Local Knowledge Base 检索规则

## API 事实（2026-04-25 更新）

- 本地部署的 OpenAlex 静态知识库（DuckDB + SQLite FTS5）
- **SQLite FTS5 原生支持布尔桶 + 字段 + 短语**：
  - 布尔：`AND` / `OR` / `NOT` / `NEAR()`
  - 括号分组：`(A OR B) AND (C OR D)`
  - 字段限定：`title:X` / `abstract_preview:Y` / `authors:Z`
  - 精确短语：`"quoted phrase"`
  - 前缀：`transform*`
- **BM25 排序**（title 权重 10×，abstract 5×，authors 2×）
- **jieba 中文分词**自动应用，中英文混合查询都能 token 化
- 支持**引用图扩展**（1-hop 从 BM25 top-20 出发）
- 毫秒级查询，无网络

## 适合主题

- 任何主题（覆盖面广）
- 尤其适合：
  - 离线场景
  - 引用网络分析
  - 快速主题探索（不等 API）

## 三层降级的关键词生成规则

### complex 层（精度 + 召回）
- **3-4 个同义词桶**，每桶 2-3 个中英文混合词
- 可叠字段限定 `title:` / `abstract_preview:` / `authors:`
- 示例：
  - `(锂电池 OR LFP OR lithium) AND (正极 OR 电极 OR cathode) AND (涂层 OR coating)`
  - `(title:CRISPR OR title:"gene editing") AND (cancer OR tumor OR 癌症)`
  - `(爆珠 OR 胶囊 OR capsule) AND (滴制 OR 成型 OR forming) AND (烟草 OR tobacco)`

### medium 层
- **2 个同义词桶**
- 示例：`(锂电池 OR lithium) AND (正极 OR cathode)`

### simple 层
- 2-3 词纯空格（fetcher 会自动用 OR 连接）
- 示例：`锂电池 正极 涂层`

## 禁止

- 超过 4 个桶（FTS5 parser 能处理但 BM25 排序会稀释）
- 孤立的 `*`（非前缀用途）或 `-`（FTS5 用 `NOT` 否定）
- 超过 2 个 `"phrase"` 短语（短语越严召回越低）

## 示例对照

| 研究主题 | ✅ complex | ✅ medium | ✅ simple |
|---|---|---|---|
| 烟草爆珠 | `(爆珠 OR 胶囊 OR capsule) AND (滴制 OR forming) AND (烟草 OR tobacco)` | `(爆珠 OR 胶囊) AND (烟草 OR tobacco)` | `爆珠 滴制 烟草` |
| 锂电池正极 | `(锂电池 OR LFP OR lithium) AND (正极 OR 电极 OR cathode) AND (涂层 OR coating)` | `(锂电池 OR lithium) AND (正极 OR cathode)` | `锂电池 正极 涂层` |
| CRISPR 治疗 | `(title:CRISPR OR title:"gene editing") AND (cancer OR 癌症)` | `(CRISPR OR "gene editing") AND (cancer OR tumor)` | `CRISPR cancer therapy` |
