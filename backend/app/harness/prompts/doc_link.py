"""
Document-document 语义关系推断 prompt。

输入：N 对文献（每对含双方 title + one_line_summary + 2-3 条 ai_key_points）
输出：每对 {edge_type, reason, confidence} 或 abstain
"""

VALID_DOC_EDGE_TYPES = {
    "extends",       # A 是 B 的延伸 / 改进
    "refutes",       # A 反驳 / 挑战 B 的结论
    "parallel",      # A 与 B 是同一问题的并列方案
    "surveys",       # A 是 B 所在领域的综述
    "replicates",    # A 是 B 的复现 / 验证
    "applies",       # A 将 B 的方法应用到新场景
}


DOC_LINK_SYSTEM_PROMPT = """你是科研文献关系分析专家。

## 任务
给你 N 对文献，每对都有可能共享主题。基于它们的摘要 + 关键要点，判断文献之间是否存在**明确**的研究关系。

## 规则
1. 只有关系**清晰有证据**时才给出判断；模糊 / 无关 → `abstain=true`
2. 可选 `edge_type` 白名单：{edge_types}
3. `reason` 一句中文（≤80 字），**基于两篇文献的内容**，不要泛泛而谈
4. `confidence` 0-1；< 0.6 会被过滤
5. **方向**：从 A 视角看 B。A extends B → `extends`；A 是 B 的综述 → `surveys`
6. 少即是多，宁可 abstain 也不要编造
7. 输出顺序必须与输入对一一对应

## 关系类型参考
- `extends` — A 继承 B 的核心思路并扩展
- `refutes` — A 的结论与 B 相反或挑战 B
- `parallel` — A 与 B 是同类问题的并列解法
- `surveys` — A 综述包含 B 在内的一批工作
- `replicates` — A 复现 / 验证 B 的实验
- `applies` — A 把 B 的方法应用到新领域

## 输出格式（严格 JSON 数组，无任何额外文字）
```json
[
  {{"abstain": false, "edge_type": "extends", "reason": "A 在 B 的 SAM 架构上新增多模态编码器", "confidence": 0.88}},
  {{"abstain": true}}
]
```"""


DOC_LINK_USER_PROMPT = """请判断以下 {n} 对文献的关系：

{pairs_context}

仅输出 JSON 数组（{n} 个元素，顺序与上面一致），不要任何其他文字。"""


def build_doc_link_prompt(pairs_with_context: list[dict]) -> tuple[str, str]:
    """
    Args:
        pairs_with_context: [
            {
              "doc_a": {"title": ..., "summary": ..., "key_points": [...]},
              "doc_b": {...},
            }, ...
        ]
    """
    lines: list[str] = []
    for i, p in enumerate(pairs_with_context, 1):
        a = p.get("doc_a") or {}
        b = p.get("doc_b") or {}
        lines.append(f"### 对 #{i}")
        lines.append(f"**A**: {a.get('title', 'Unknown')[:120]}")
        if a.get("summary"):
            lines.append(f"  摘要: {a['summary'][:200]}")
        for kp in (a.get("key_points") or [])[:3]:
            lines.append(f"  · {str(kp)[:100]}")
        lines.append(f"**B**: {b.get('title', 'Unknown')[:120]}")
        if b.get("summary"):
            lines.append(f"  摘要: {b['summary'][:200]}")
        for kp in (b.get("key_points") or [])[:3]:
            lines.append(f"  · {str(kp)[:100]}")
        lines.append("")

    pairs_context = "\n".join(lines) if lines else "（无）"
    system = DOC_LINK_SYSTEM_PROMPT.format(
        edge_types=", ".join(sorted(VALID_DOC_EDGE_TYPES))
    )
    user = DOC_LINK_USER_PROMPT.format(
        n=len(pairs_with_context),
        pairs_context=pairs_context,
    )
    return system, user
