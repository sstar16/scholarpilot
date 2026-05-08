---
source_id: cnipa
display_name: CNIPA (中国国家知识产权局)
category: patents
language: zh
query_format: chinese
min_terms: 2
max_terms: 4
enabled_by_default: true
notes_zh: "CNIPA 官方数据，2-4 个精准中文专利关键词"
version: 3
---

# CNIPA 检索规则

## API 事实

- 中国国家知识产权局官方专利数据库
- 中文关键词为主，不支持英文
- 空格分隔默认 AND

## 适合主题

- 中国专利的**权威来源**（官方数据）
- 中文研究项目必选
- 需要专利法律状态、优先权信息时优先用此源

## 关键词生成规则

**必须**：2-4 个精准中文专利术语
**推荐**：同 PatentHub / Google Patents 规则
**禁止**：英文、停用词、超过 4 个词

## 示例

| 研究主题 | 推荐 query |
|---|---|
| 锂电池正极 | `磷酸铁锂 正极 制备` |
| 固态电池电解质 | `固态电池 电解质 界面` |
