---
name: graph_extraction
version: 1
description: Extract entities and relations from a research paper for knowledge graph construction
model_hint: sonnet
temperature: 0.1
max_retries: 2
entity_count_min: 2
entity_count_max: 5
relation_count_min: 1
relation_count_max: 3
---

你是知识图谱抽取专家。从下面这篇论文 / 专利的标题、摘要、（可选）全文，抽取知识图谱实体和关系。

# 输入
Title: $title
Authors: $authors
Year: $year
Abstract: $abstract
Fulltext (optional):
$fulltext

# 实体类型 enum (V1 6 类)
- paper: 论文 / 专利（自身）
- concept: 关键概念 / 术语
- author: 作者
- organization: 机构
- method: 方法 / 算法
- technology: 技术 / 工具

# 关系类型 enum (V1 6 类)
- cites: 引用
- extends: 延伸 / 扩展
- contradicts: 反驳
- coauthor: 共著
- topic: 主题归属
- method_of: 方法归属

# 输出（**严格 JSON**，不要 markdown 代码块，不要任何解释文字）
{
  "entities": [
    {"label": "string", "type": "paper|concept|author|organization|method|technology", "weight": 0.0}
  ],
  "relations": [
    {"source": "string", "target": "string", "relation": "cites|extends|contradicts|coauthor|topic|method_of", "weight": 0.0}
  ]
}

# 要求
- entities 数量 2-5 个；relations 数量 1-3 个
- weight 是 0.0-1.0 浮点数，反映重要性 / 置信度
- relation 的 source 和 target 必须是 entities 里出现过的 label
- 不要 hallucinate paper 之外不能从输入推出的实体
- 输出必须是合法 JSON：所有字符串用双引号，最后一个字段不要有逗号
- 不要返回 ```json``` 代码块，直接输出 JSON 对象
