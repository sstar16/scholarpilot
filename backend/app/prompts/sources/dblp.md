---
source_id: dblp
display_name: DBLP
category: literature
language: en
query_format: boolean_lite
min_terms: 2
max_terms: 3
max_phrases: 1
enabled_by_default: true
notes_zh: "CS 会议/期刊，2-3 词 + 可用 | OR 和短语引号"
version: 4
---

# DBLP 检索规则

## API 事实（2026-04-24 实测更新）

- **只覆盖计算机科学**（ACM/IEEE/Springer 的顶会和顶刊）
- **前缀匹配**：搜 "trans" 会匹配 "transformer", "translation", "transactions"
- **实测支持**：
  - `|` 作为 OR（如 `transformer|attention` → 105749 条，vs `transformer attention` 3753 条）
  - `"quoted phrase"` 精确短语（如 `"attention is all you need"` → 107 条）
  - `$` 作为模糊匹配（如 `transform$` 匹配 transform* 前缀变体）
- **不支持**显式 `AND/OR`（会被当关键词）
- 严格控制 2-3 个核心词；前缀匹配 + 多词叠加容易过拟合

## 适合主题

- CS 顶会论文：CVPR, NeurIPS, ACL, ICML, SIGMOD, OSDI, SOSP 等
- CS 顶刊：TPAMI, TOG, JMLR, TOCS 等
- **不适合**：非 CS 领域（返回 0 结果）

## 三层降级的关键词生成规则

### complex 层（精度优先，有一个选项：精确短语 OR 近义词 OR）
- 精确模式：`"exact paper topic"`（1 个短语，如追踪特定领域经典论文）
- 近义扩展模式：`term1|term2`（如 `transformer|attention`，两个近义概念 OR）
- 示例：
  - `"federated learning"`
  - `transformer|attention efficient`
  - `"zero-shot retrieval"`

### medium 层
- 2-3 个核心 CS 术语，纯空格
- 示例：`transformer pretraining`

### simple 层（兜底）
- 1-2 个最具体的 CS 术语 / 子领域名 / 缩写
- 示例：`transformer` 或 `GAN` 或 `federated`

## 禁止

- 超过 3 个词（前缀匹配叠加容易 0 命中）
- 显式 `AND/OR/NOT`（会被当普通关键词，污染结果）
- 中文
- Generic CS 词（algorithm, model, learning, system — 太宽泛）

## 非 CS 项目

- **应主动禁用此源**。Adapter 生成的 query 无论如何也会返回 0 结果。
