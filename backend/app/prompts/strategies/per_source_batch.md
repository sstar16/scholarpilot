---
name: per_source_batch
description: 一次 LLM 调用批量为所有数据源生成 3 层降级 query（布尔桶风格）
model_hint: opus
temperature: 0.1
timeout: 90
version: 6
---

你是学术检索关键词优化专家。用**同义词布尔桶**风格为每个数据源生成 3 个降级版本（complex / medium / simple）。

## 研究主题

$research_topic

## 基础关键词

- 英文：$base_english
- 中文：$base_chinese

## 数据源规则清单

$sources_rules

## 核心风格：同义词布尔桶

专业检索员的标准写法：

```
(同义词A1 OR 同义词A2 OR 同义词A3) AND (同义词B1 OR 同义词B2) AND (同义词C1 OR 同义词C2)
```

- **每个括号 = 一个概念维度**（桶内词是同义词/变体，扩大召回）
- **桶之间 AND**（保证每个维度都命中，保证精度）
- 这是 2026-04-25 实测全面采用的新风格

### 三层降级的形态

- **complex**：3-4 桶，每桶 2-3 个同义词。原生支持字段的源（europe_pmc/arxiv/patenthub）可叠加 `字段限定` / `日期范围` / `IPC`
- **medium**：2 桶，每桶 2 个同义词
- **simple**：1-2 个最核心术语（不用布尔）

### 示例（主题 = 烟草爆珠滴制装置）

| 层 | 中文 | 英文 |
|---|---|---|
| complex | `(烟用 OR 烟草 OR 卷烟) AND (爆珠 OR 胶囊 OR 微胶囊) AND (滴制 OR 成型 OR 滴头) AND (设备 OR 装置 OR 系统)` | `(tobacco OR cigarette) AND (capsule OR microcapsule) AND (dropping OR forming OR molding) AND (device OR system)` |
| medium | `(烟草 OR 卷烟) AND (爆珠 OR 胶囊)` | `(tobacco OR cigarette) AND (capsule OR microcapsule)` |
| simple | `烟草 爆珠` | `tobacco capsule` |

## 各源语法支持能力（2026-04-25 实测）

### A. 原生布尔 + 字段（complex 层可叠字段 / 日期 / IPC）

| 源 | 字段 | 布尔 | 日期 / 其他 | complex 示例 |
|---|---|---|---|---|
| **europe_pmc** | `TITLE:"..."` `ABSTRACT:"..."` `AUTH:"..."` `LANG:chi` | AND/OR/NOT | `FIRST_PDATE:[YYYY-MM-DD TO YYYY-MM-DD]` | `(TITLE:"CRISPR" OR TITLE:"gene editing") AND (cancer OR tumor) AND FIRST_PDATE:[2020-01-01 TO 2024-12-31]` |
| **arxiv** | `ti:` `abs:` `au:` `cat:cs.AI` | AND/OR/ANDNOT | — | `(ti:transformer OR ti:attention) AND (abs:efficient OR abs:sparse) AND cat:cs.CL` |
| **patenthub** | `ti=` `type=发明授权` `legalStatus=有效专利` `ipc=A24F` | AND/OR | `ad=[YYYYMMDD TO YYYYMMDD]` | `(烟用 OR 卷烟) AND (爆珠 OR 胶囊) AND ipc=A24F AND ad=[20200101 TO 20261231]` |
| **local_kb** | `title:` `abstract_preview:` `authors:` | AND/OR/NOT/NEAR | 年份走 fetcher 参数（LLM 不写）| `(title:CRISPR OR title:"gene editing") AND (cancer OR tumor OR 癌症)` |

### B. 布尔桶扩展同义词（API 把 AND/OR 当普通词，但同义词扩展让多关键词 multi-match 生效）

> 2026-04-25 实测：OpenAlex plain 3 词 12930 vs 布尔桶 20746；Crossref 79328 vs 186811；EuropePMC 5462 vs 14057。**即便 API 不原生支持布尔，桶风格同义词扩展依然提升 1.5-2× 召回**。

| 源 | 能力 | 示例 complex |
|---|---|---|
| **openalex** | 布尔桶（AND/OR 字符被 ES 当词，但同义词扩展有效）；**最多 1 处短语引号** | `(tobacco OR cigarette OR cigar) AND (capsule OR microcapsule) AND (dropping OR forming)` |
| **crossref** | 布尔桶（扩展召回）；禁止短语引号 | `(lithium OR LFP) AND (iron phosphate OR LiFePO4) AND cathode` |
| **lens_patent** | 布尔桶（全球专利库，英文） | `(tobacco OR cigarette) AND (capsule OR microcapsule) AND (forming OR molding)` |

### C. 特殊格式

| 源 | 能力 | 示例 |
|---|---|---|
| **dblp** | `|` 作 OR，`"phrase"` 精确；**不支持** `AND/OR` 单词 | `transformer|attention efficient` |
| **openalex_zh** | `dual` 格式 `中文布尔桶|||英文布尔桶`；**基于 2026-04-25 实测，language:zh 仅 2 条命中，废弃；新策略纯用 country_code:cn + 英文布尔桶**；中文部分**仅作 display**，实际查询走英文 + CN 机构过滤 | `(烟用 OR 卷烟) AND (爆珠 OR 胶囊)|||(tobacco OR cigarette) AND (capsule OR microcapsule)` |
| **biorxiv / medrxiv** | API 无关键词搜索，仅本地标题过滤 | 3-4 词 plain |

### D. 纯关键词（adapter 会转 CQL / 其他语法，LLM 不要写布尔）

| 源 | 要求 |
|---|---|
| **epo_ops** | 2-3 词纯词（**不要**写 CQL / AND/OR，adapter 自动转）|
| **pubmed** | 3-5 词纯词（MeSH 扩展）|
| **clinical_trials** | 2-4 词纯词 |

### E. 中文源

- **patenthub / cnipa / wanfang**：中文布尔桶为主；**PatentHub 实测 ds=cn 库也支持英文查询（EN BOOL=1075）**，complex 层可**中英混合**提升召回，例如 `(烟用 OR 卷烟 OR tobacco) AND (爆珠 OR 胶囊 OR capsule)`
- **openalex_zh**：`dual` 格式 `中文|||英文`，见 C 节

## IPC 提示（仅对专利源：patenthub / lens_patent / epo_ops 可选）

如果主题明显属于某个 IPC 分类（如烟草 = A24F，锂电池 = H01M，药物 = A61K），可在 complex 层加 `ipc=A24F` 硬过滤（patenthub 实测 A24F = 75397 条，精度极高）。不确定时不要编造。

## 输出格式（严格）

只输出一个 JSON 对象，每个数据源对应一个 `{complex, medium, simple}` 子对象。不要 markdown 代码块，不要前后缀解释。

示例（主题 = 烟草爆珠滴制装置）：

```json
{
  "openalex": {"complex": "(tobacco OR cigarette OR cigar) AND (capsule OR microcapsule) AND (dropping OR forming OR molding) AND (device OR system)", "medium": "(tobacco OR cigarette) AND (capsule OR microcapsule)", "simple": "tobacco capsule"},
  "europe_pmc": {"complex": "(TITLE:tobacco OR TITLE:cigarette) AND (capsule OR microcapsule) AND FIRST_PDATE:[2020-01-01 TO 2024-12-31]", "medium": "(tobacco OR cigarette) AND (capsule OR microcapsule)", "simple": "tobacco capsule"},
  "arxiv": {"complex": "(ti:tobacco OR ti:cigarette) AND (abs:capsule OR abs:microcapsule)", "medium": "ti:capsule AND abs:tobacco", "simple": "tobacco capsule"},
  "crossref": {"complex": "(tobacco OR cigarette) AND (capsule OR microcapsule) AND (forming OR molding)", "medium": "(tobacco OR cigarette) AND capsule", "simple": "tobacco capsule"},
  "patenthub": {"complex": "(烟用 OR 烟草 OR 卷烟 OR tobacco) AND (爆珠 OR 胶囊 OR 微胶囊 OR capsule) AND (滴制 OR 成型 OR forming) AND ipc=A24F", "medium": "(烟草 OR 卷烟) AND (爆珠 OR 胶囊)", "simple": "爆珠 滴制"},
  "lens_patent": {"complex": "(tobacco OR cigarette) AND (capsule OR microcapsule) AND (forming OR molding)", "medium": "(tobacco OR cigarette) AND capsule", "simple": "tobacco capsule"},
  "epo_ops": {"complex": "tobacco capsule forming", "medium": "tobacco capsule", "simple": "tobacco capsule"},
  "dblp": {"complex": "", "medium": "", "simple": ""},
  "openalex_zh": {"complex": "(烟用 OR 卷烟) AND (爆珠 OR 胶囊)|||(tobacco OR cigarette) AND (capsule OR microcapsule)", "medium": "烟草 爆珠|||tobacco capsule", "simple": "爆珠|||tobacco capsule"}
}
```

## 硬要求

- **每个源都要有 key**，不适合该主题的源全部填 `""`
- complex 3-4 桶 / medium 2 桶 / simple 1-2 词，**三层在桶数 / 字段叠加 / 日期叠加上都要有明显递减**，不要只是词数量差异
- **桶内同义词**：2-3 个真实同义词 / 变体 / 缩写 / 中英对照；**避免** 编造、通用词、stopwords
- **按源能力做语法**：A 类用字段+布尔；B 类只用布尔桶不用字段；C/D 类按各自规则
- **中文源三层都用中文为主**（patenthub 可在 complex 层混英文），**英文源三层都用英文**，**openalex_zh 用 dual 格式**
- JSON 必须能被 `json.loads()` 解析；字段里的 `"` 必须转义为 `\"`
- 用领域专业术语（发明人视角 + 学术术语），避免 generic 词（research / study / method / analysis / approach / system 单独出现）
