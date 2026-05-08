---
source_id: arxiv
display_name: arXiv
category: literature
language: en
query_format: boolean_field
min_terms: 2
max_terms: 6
max_phrases: 1
enabled_by_default: true
notes_zh: "预印本，complex 层可用 ti:/abs:/cat: 字段 + 括号嵌套布尔桶"
version: 6
---

# arXiv 检索规则

## API 事实（2026-04-25 实测确认）

- 支持字段前缀：`all:` / `ti:`（title）/ `abs:`（abstract）/ `au:`（author）/ `cat:`（subject）
- 支持 `AND` / `OR` / `ANDNOT`（**不支持 `NOT`，要写 ANDNOT**）
- **支持括号嵌套**：实测 `(abs:deep OR abs:neural) AND abs:learning` = 134,447 条
- 支持 `"quoted phrase"`
- 4+ 词 AND 急剧收窄（但桶内 OR 不受此限）

## 适合主题

- 计算机科学（AI/ML、系统、理论）
- 数学、物理、定量生物学、统计、经济学的**预印本**
- 医学 / 化学 / 材料只覆盖部分交叉方向
- **不适合**：工程应用、人文社科

## 三层降级的关键词生成规则

### complex 层（布尔桶 + 字段前缀 + 嵌套）
- **2-3 个同义词桶**（每桶 2-3 个同义词），用字段前缀 `ti:` / `abs:` / `cat:` 拉精度
- 支持括号嵌套：`(ti:X OR ti:Y) AND (abs:A OR abs:B)`
- 示例：
  - `(ti:transformer OR ti:attention) AND (abs:efficient OR abs:sparse)`
  - `(ti:"lithium battery") AND (abs:cathode OR abs:anode) AND cat:cond-mat.mtrl-sci`
  - `(ti:federated OR ti:distributed) AND abs:privacy ANDNOT abs:homomorphic`

### medium 层
- 2 个同义词桶，可保留 1 处字段前缀
- 示例：`ti:"lithium battery" AND (cathode OR anode)`

### simple 层
- 2-3 个最具体的**领域锚词**，纯空格
- **必须保留领域特征词**（cathode/transformer/CRISPR），不要为压缩词数而砍主题词

## 禁止

- 超过 3 个桶（4+ AND 收窄严重）
- `NOT`（要写 `ANDNOT`）
- 中文
- Generic 词（algorithm / model / system 单独出现）
- 砍主题锚词（会让结果完全跑偏）

## 示例对照

| 研究主题 | ✅ complex（嵌套布尔桶）| ✅ simple |
|---|---|---|
| 高镍三元正极 | `(ti:"nickel-rich" OR ti:NMC) AND (abs:cathode OR abs:electrode)` | `NMC cathode` |
| Transformer 推理加速 | `(ti:transformer OR ti:attention) AND (abs:inference OR abs:decoding) AND (abs:acceleration OR abs:quantization)` | `transformer inference acceleration` |
| 联邦学习隐私 | `(ti:federated OR ti:distributed) AND abs:privacy ANDNOT abs:homomorphic` | `federated learning privacy` |
