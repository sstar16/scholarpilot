"""
Concept-concept 语义关系推断 prompt（批量，一次送 N 对）。

输入：多对共现 concept（每对带 label + 两边各自所在文献的一句话摘要）
输出：每对一个 JSON object，说明关系类型 + 一句话理由 + 置信度；或 abstain
"""

# 关系类型白名单 —— 解析器严格按此过滤
VALID_EDGE_TYPES = {
    "same_as",         # 同义 / 指代同一事物
    "sub_concept",     # A 是 B 的子概念 / 具体实现
    "parent_concept",  # A 是 B 的上位概念
    "causes",          # A 导致 / 驱动 B
    "precedes",        # A 是 B 的前置条件 / 历史先驱
    "contrasts",       # A 与 B 是对立 / 竞争方案
    "related_method",  # 相关但独立的方法 / 技术同类
}


CONCEPT_LINK_SYSTEM_PROMPT = """你是科研领域的概念关系专家。

## 任务
给你 N 对概念，每对都在多篇文献里共同出现。基于它们各自所在文献的一句话摘要，判断它们之间是否存在**明确**的语义关系。

## 规则
1. 有**明确语义联系**时就给出 edge_type；即使 A 与 B 只是**同领域的并列方法/概念**也可以用 `related_method`（降低 abstain 门槛）
2. 真正**毫无关联**时才 `abstain=true`
3. 可选 `edge_type` 白名单（只能取其一）：{edge_types}
4. `reason` 必须是一句话中文（≤80 字），**基于文献证据**，不要泛泛而谈
5. `confidence` 取值 0-1；< 0.5 会被过滤
6. **方向**：从 A 视角看 B。A is_a B → `sub_concept`；A 是 B 的父概念 → `parent_concept`；不要左右纠结
7. 不要编造关系，但鼓励在**有合理理由**时给出
8. 输出顺序必须与输入顺序一一对应

## 输出格式（严格 JSON 数组，无任何额外文字）
```json
[
  {{"abstain": false, "edge_type": "sub_concept", "reason": "A 是 B 的具体实现，论文 X/Y 都用 A 作为 B 的例子", "confidence": 0.85}},
  {{"abstain": true}},
  {{"abstain": false, "edge_type": "related_method", "reason": "两者都是解决同类问题的并列方法", "confidence": 0.72}}
]
```"""


CONCEPT_LINK_USER_PROMPT = """请判断以下 {n} 对概念的关系：

{pairs_context}

仅输出 JSON 数组（{n} 个元素，顺序与上面一致），不要任何其他文字。"""


def build_concept_link_prompt(pairs_with_context: list[dict]) -> tuple[str, str]:
    """
    Args:
        pairs_with_context: [
            {
              "concept_a": "概念 A label",
              "a_summaries": ["文献摘要 1", ...],
              "concept_b": "概念 B label",
              "b_summaries": ["文献摘要 1", ...],
            }, ...
        ]
    Returns:
        (system_prompt, user_prompt)
    """
    lines: list[str] = []
    for i, p in enumerate(pairs_with_context, 1):
        lines.append(f"### 对 #{i}")
        lines.append(f"**A**: {p['concept_a']}")
        for s in (p.get("a_summaries") or [])[:4]:
            lines.append(f"  · {s}")
        lines.append(f"**B**: {p['concept_b']}")
        for s in (p.get("b_summaries") or [])[:4]:
            lines.append(f"  · {s}")
        lines.append("")

    pairs_context = "\n".join(lines) if lines else "（无）"
    system = CONCEPT_LINK_SYSTEM_PROMPT.format(
        edge_types=", ".join(sorted(VALID_EDGE_TYPES))
    )
    user = CONCEPT_LINK_USER_PROMPT.format(
        n=len(pairs_with_context),
        pairs_context=pairs_context,
    )
    return system, user
