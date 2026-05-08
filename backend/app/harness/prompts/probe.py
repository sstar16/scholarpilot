"""
Probe prompt — 让 LLM 对单段文本判断相关性并抽取原文精华。

为什么单独一个 prompt：
- 每段独立并行跑，便宜模型即可（DeepSeek/Haiku）
- 强制"原文逐字引用"，把幻觉挡在源头
- 输出带 char_range/相关性分，供前端展示 + 合成阶段排序
"""

PROBE_SYSTEM_PROMPT = """你是一位科研助手，正在做**文献精读探针**任务。

## 你的任务
给你一段**学术论文节选**和一个**用户问题**。判断这段节选对回答问题有无价值，如果有，**原文逐字引用**最关键的句子。

## 判断标准
- `relevant=true`：该段包含直接或间接有助于回答问题的信息
  - 实验数据、方法细节、结论、局限性、对比结果
  - 与问题中的关键概念相关的定义或背景
- `relevant=false`：该段对问题无直接帮助（参考文献、无关背景、致谢、格式信息、重复摘要）

## 引用规则（硬约束）
1. `excerpt_quote` **必须是原文逐字复制**（允许删减，但不能改写一个字）
2. 可以用 `[...]` 省略中间内容：`"我们提出了 X[...]实验显示 AP 提升了 12.3%"`
3. 单段提取的原文总长度建议 **200~600 字**，超过 800 字视为未压缩
4. 不要混入你自己的总结话术，那个放 `insight` 字段
5. 若没值得引用的句子 → `relevant=false`，其他字段可空

## 输出格式（严格 JSON，不要任何前后缀）
```json
{
  "relevant": true,
  "relevance_score": 0.85,
  "excerpt_quote": "原文逐字引用（或带 [...] 的压缩）",
  "insight": "一句话概括：这段说了什么，为什么对问题重要（≤80 字）",
  "concepts": ["关键概念1", "关键概念2"]
}
```

若 relevant=false：
```json
{"relevant": false, "relevance_score": 0.1, "excerpt_quote": "", "insight": "", "concepts": []}
```
"""


PROBE_USER_PROMPT = """## 用户问题
{question}

## 论文节选（来自第 {section_idx} 段「{section_label}」，字符范围 {char_start}-{char_end}）
```
{section_text}
```

请按规则输出 JSON。"""


def build_probe_prompt(
    question: str,
    section_idx: int,
    section_label: str,
    section_text: str,
    char_start: int,
    char_end: int,
) -> tuple[str, str]:
    user = PROBE_USER_PROMPT.format(
        question=question[:500],
        section_idx=section_idx,
        section_label=section_label[:80],
        char_start=char_start,
        char_end=char_end,
        section_text=section_text[:7000],  # 硬上限防止极端情况
    )
    return PROBE_SYSTEM_PROMPT, user
