---
source_id: patenthub
display_name: PatentHub (中国专利)
category: patents
language: zh
query_format: boolean_field
min_terms: 2
max_terms: 14
max_phrases: 0
enabled_by_default: true
notes_zh: "专利汇 API，中英混合布尔桶 + IPC 分类号 + ad 日期范围"
version: 5
---

# PatentHub 检索规则

## API 事实（2026-04-25 实测确认）

- 覆盖中国全部专利 + WIPO + 部分海外（`ds=cn` 中国 / `ds=wo` 世界，默认 cn 即可）
- 搜索 ¥0.1/次，PDF ¥1/次（走 `services/patenthub_budget.py` 守门）
- **实测（主题 = 烟草爆珠）**：
  - plain 3 词 `烟用 爆珠 滴制` → 89
  - 2 桶布尔 `(烟用 OR 烟草 OR 卷烟) AND (爆珠 OR 胶囊 OR 微胶囊)` → **3,348（+37×）**
  - 4 桶过严 → 154（过度收窄）
  - **中英混合** `(烟用 OR 卷烟 OR tobacco) AND (爆珠 OR 胶囊 OR capsule)` → ds=cn 有 1,075 条英文命中（**CN 专利摘要大量带英文版**）
  - `ipc=A24F`（烟草分类） → 75,397（IPC 过滤极强）
  - `ad=[20200101 TO 20261231]` → 年份过滤生效
- **支持语法**：`AND/OR`、`ti=` / `type=发明授权` / `legalStatus=有效专利` / `ipc=XXX` / `ad=[YYYYMMDD TO YYYYMMDD]`
- 空格默认 AND
- 不支持双引号短语

## 适合主题

- 中国专利（最完整 CN 专利库之一）
- 中文研究项目 **必选**
- 工业应用、工艺、配方、设备类
- 技术可实施性评估、专利动向

## 三层降级的关键词生成规则

### complex 层（精度 + 召回最优）
- **2-3 个同义词桶**（不要 4 桶，实测过严）
- **中英混合鼓励**：每桶同时放中文词 + 英文词（CN 库吃英文 query）
- 可叠：`ipc=XXX`（强烈推荐，烟草=A24F / 锂电池=H01M / 药物=A61K 等）/ `type=发明授权` / `ad=[YYYYMMDD TO YYYYMMDD]`
- 示例：
  - `(烟用 OR 卷烟 OR tobacco) AND (爆珠 OR 胶囊 OR capsule) AND ipc=A24F`
  - `(固态电池 OR solid-state battery) AND (电解质 OR electrolyte) AND type=发明授权`
  - `(磷酸铁锂 OR LFP OR LiFePO4) AND (正极 OR cathode) AND ad=[20200101 TO 20261231]`

### medium 层
- **2 个同义词桶**，纯中文或中英混合，不加字段
- 示例：`(烟草 OR 卷烟) AND (爆珠 OR 胶囊)`

### simple 层
- 1-2 个最核心中文技术词，纯空格
- 示例：`爆珠 滴制`

## IPC 分类号提示

专利检索的杀手锏。如果主题明确属于某个分类，complex 层**强烈建议**叠 `ipc=XXXX`：

| 主题 | 推荐 IPC |
|---|---|
| 烟草制品 | A24F |
| 锂电池 / 燃料电池 | H01M |
| 药物组合物 | A61K |
| 农药 / 除草剂 | A01N |
| 半导体 | H01L |
| 有机化合物 | C07 |
| 金属合金 | C22C |

不确定时不要编造 IPC。

## 禁止

- 超过 3 个桶（实测 4 桶从 3348 降到 154）
- 停用词（"的"、"和"、"研究"、"方法"、"技术"单独出现）
- 双引号短语
- 纯英文 without 中文（英文能查但中文是主力，应中英混合）
- complex 层堆 ≥3 个字段限定（过窄）

## 示例对照

| 研究主题 | ✅ complex | ✅ medium | ✅ simple |
|---|---|---|---|
| 烟草爆珠滴制 | `(烟用 OR 卷烟 OR tobacco) AND (爆珠 OR 胶囊 OR capsule) AND ipc=A24F` | `(烟草 OR 卷烟) AND (爆珠 OR 胶囊)` | `爆珠 滴制` |
| 固态电池电解质 | `(固态电池 OR "solid-state battery") AND (电解质 OR electrolyte OR 界面) AND type=发明授权` | `(固态电池 OR 锂电池) AND 电解质` | `固态电池 电解质` |
| 智能手表健康 | `(智能手表 OR smartwatch) AND (健康 OR 监测 OR health) AND ad=[20230101 TO 20261231]` | `(智能手表) AND (健康 OR 监测)` | `智能手表 健康` |
