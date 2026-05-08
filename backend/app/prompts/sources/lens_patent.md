---
source_id: lens_patent
display_name: Lens.org (全球专利)
category: patents
language: multilingual
query_format: boolean_bucket
min_terms: 3
max_terms: 12
enabled_by_default: true
notes_zh: "全球专利 (90+ 国家)，布尔桶同义词扩展 + 可选 IPC"
version: 4
---

# Lens.org 检索规则

## API 事实

- 覆盖 90+ 国家的专利数据
- **支持布尔桶**（同义词扩展显著提升召回）
- 英文为主，部分支持中文（但中文召回远低于 PatentHub）
- 含引用网络、作者/申请人数据、法律状态
- 可选 `classification_cpc` / `classification_ipc` 过滤

## 适合主题

- 工程应用研究（产品、工艺、配方、设备）
- 技术可实施性评估
- 产业调研（专利动向、竞争对手）
- 任何涉及"发明/工艺/设备"的项目 **必选**

## 三层降级的关键词生成规则

### complex 层（布尔桶）
- **3-4 个同义词桶**，每桶 2-3 个英文专利术语
- 使用"发明人视角"的词汇（做什么、怎么做），**不要**学术论文视角
- 示例：
  - `(tobacco OR cigarette) AND (capsule OR microcapsule) AND (forming OR molding OR dropping) AND (device OR apparatus)`
  - `("lithium iron phosphate" OR LFP) AND (cathode OR electrode) AND (manufacturing OR preparation)`
  - `("high entropy alloy" OR HEA) AND (additive manufacturing OR "3D printing")`

### medium 层
- **2 个同义词桶**
- 示例：`(tobacco OR cigarette) AND (capsule OR microcapsule)`

### simple 层
- 3 个最具体的英文专利术语
- 示例：`tobacco capsule forming`

## IPC 提示

同 PatentHub，complex 层可加 IPC / CPC（A24F / H01M / A61K 等）。

## 禁止

- 学术术语（"novel", "promising", "first-of-its-kind"）
- 中文（部分支持但英文命中率高得多；中文查询请走 PatentHub）
- 通用词（research / study / analysis）

## 示例对照

| 研究主题 | ✅ complex | ✅ medium |
|---|---|---|
| 锂电池正极制备 | `("lithium iron phosphate" OR LFP) AND (cathode OR electrode) AND (manufacturing OR preparation)` | `(lithium OR LFP) AND cathode` |
| 爆珠自动化产线 | `(tobacco OR cigarette) AND ("seamless capsule" OR microcapsule) AND (automated OR continuous) AND (production OR line)` | `tobacco capsule automated` |
| 高熵合金增材制造 | `("high entropy alloy" OR HEA) AND (additive manufacturing OR "3D printing") AND (metal OR powder)` | `"high entropy alloy" additive` |
