---
source_id: clinical_trials
display_name: ClinicalTrials.gov
category: clinical
language: en
query_format: plain
min_terms: 2
max_terms: 4
max_phrases: 0
enabled_by_default: false
notes_zh: "美国临床试验注册库，2-4 英文词，仅对人类临床干预研究有用"
version: 3
---

# ClinicalTrials.gov 检索规则

## API 事实

- 美国国立卫生研究院的临床试验注册数据库
- 覆盖全球注册的临床试验（人类干预研究）
- 返回的是"试验方案"不是"文献"
- 默认禁用，需手动启用
- **注意**：只收录干预性研究（Interventional）、观察性研究（Observational）等临床试验，不是普通医学文献

## 适合主题

- **医学临床研究**（仅限人类试验）：
  - 新药临床试验
  - 新治疗方案效果验证
  - 疫苗试验
  - 医疗器械临床评估
  - 流行病学队列研究
- 药物安全性和剂量探索

## 不适合主题（重要！）

- **基础生物学研究**（细胞/动物实验） → 去 PubMed / Europe PMC
- **技术研究**（材料/工程/化学工艺） → 完全不相关
- **CS / 数学 / 物理** → 完全不相关
- **专利类** → 完全不相关
- **非医学的任何主题** → 不适合

如果用户研究主题不是"人类医学试验"类，**不要给这个源生成 query**，返回空字符串让系统自动关闭它。

## 关键词生成规则

**必须**：2-4 个英文医学/治疗术语
**推荐**：
- 疾病名（疾病标准英文名）+ 干预方式（药物/器械/疗法）
- 可包含 clinical trial 相关词（phase/randomized/placebo）

**禁止**：
- 双引号短语
- 中文
- 超过 4 个词
- 非医学试验的主题

## 示例

| 研究主题 | 推荐 query | 是否适合 |
|---|---|---|
| 新冠疫苗三期试验 | `COVID vaccine phase trial` | ✓ |
| CAR-T 癌症治疗 | `CAR-T lymphoma clinical` | ✓ |
| 锂电池正极材料（技术） | — | ✗ 不适合，返回空 |
| 半导体刻蚀工艺（纯材料/工艺） | — | ✗ 不适合，返回空 |
