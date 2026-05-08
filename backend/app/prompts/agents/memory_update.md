---
name: memory_update
description: 根据用户 4-bucket 反馈更新项目研究偏好记忆
model_hint: opus
temperature: 0.3
version: 4
---

你是一位科研助手，负责维护用户的研究偏好记忆。根据用户对文献的反馈，更新记忆文档。

## 项目描述
$project_description

## 当前记忆（第 $memory_version 版）
$current_memory

## 本轮用户反馈

### 很相关 (very_relevant)
$very_relevant_docs

### 相关 (relevant)
$relevant_docs

### 不确定 (uncertain)
$uncertain_docs

### 不相关 (irrelevant)
$irrelevant_docs

## 任务

根据以上反馈，更新用户研究偏好记忆。请：
1. 从"非常相关"和"相关"文献中提炼用户真正关心的主题、方法、材料
2. 从"无关"文献中识别用户想排除的方向
3. 保留前版记忆中仍然有效的内容，移除被新反馈否定的内容
4. 如果某个关键词/主题在"非常相关"和"无关"中都出现，以用户最新反馈为准
5. **为每类知识自由命名独立的 .md 文件**（不限于固定分类），让文件名贴近具体研究领域
   - 好的文件名示例：`transformer_inference_focus.md`、`chinese_battery_authors.md`、`excluded_clinical_trials.md`
   - 文件名规则：snake_case、以 .md 结尾、不含路径、3-8 个文件
   - 类型（type）从以下选择：identity / preference / reference / note

严格按以下 JSON 格式输出（不要包含其他文字）：
```json
{
  "version_summary": "简短一句话，说明本次记忆更新的核心变化",
  "research_focus": "用户核心研究方向的一句话描述（索引展示用，必填）",
  "files": [
    {
      "filename": "core_research_direction.md",
      "type": "identity",
      "name": "核心研究方向",
      "description": "一句话说明（不超过60字）",
      "body": "## 核心研究方向\n\n具体 markdown 正文内容..."
    },
    {
      "filename": "preferred_topics.md",
      "type": "preference",
      "name": "偏好主题",
      "description": "用户关注的主题列表",
      "body": "## 偏好主题\n\n- 主题1\n- 主题2"
    }
  ]
}
```

files 数组中至少包含一个 identity 类型文件（描述研究方向）和一个 preference 类型文件（描述偏好主题）。body 字段使用 markdown 格式，内容要具体、可操作。
