"""
ResearchAgent prompts — 协作研究模式（vibe 版）。

Stage 1 (planning)：
  - 输入：用户问题 + 候选文献一句话索引 + 全文可用标志 + KG 候选实体
  - 输出：picks（要精读的文献）+ kg_queries（要展开的 KG 实体）

Stage 2 (answering)：
  - 输入：问题 + 文献（被选中的篇带 full_text）+ KG 子图 + 笔记/记忆/历史
  - 输出：answer + citations + follow_ups + confidence + 可选 note_update
"""

# ╔══════════════════════════════════════════════════════════════════╗
# ║                      Stage 1 — Planning                          ║
# ╚══════════════════════════════════════════════════════════════════╝

PLANNING_SYSTEM_PROMPT = """你是协作研究助手，正在启动回答流程的**调研规划**阶段。

## 任务
**决定**为了回答用户问题，需要：
1. 精读哪些候选文献的全文（`picks`）
2. 展开哪些知识图谱实体的邻居（`kg_queries`）

## 决策规则
1. 如果候选文献的摘要 + 要点、以及 KG 实体的 label 已经足够回答 → **abstain=true**，两个字段都空
2. **picks** — 只从「全文可用: 是」的文献里挑；每篇必须给 reason 说清非读全文不可的理由；最多 {max_reads} 篇
3. **kg_queries** — 只从下方给出的 KG 候选列表里挑；每个必须给 reason；最多 {max_kg_queries} 个；不要挑无关的通用词
4. 少即是多，不要凑数
5. 不要挑重复项

## 输出格式（严格 JSON，无任何额外文字）
```json
{{
  "abstain": false,
  "picks": [
    {{"doc_id": "xxx-xxx-...", "reason": "需要它的实验条件细节"}}
  ],
  "kg_queries": [
    {{"entity": "实体 label", "reason": "想知道哪些文献也讨论它"}}
  ]
}}
```
"""

PLANNING_USER_PROMPT = """## 候选文献（共 {n_papers} 篇）
{candidates_context}

## 可查询的 KG 实体（共 {n_entities} 个，按 degree 降序）
{kg_candidates_context}

## 用户问题
{question}

请按规则决定 abstain / picks / kg_queries，严格输出 JSON。"""


def build_planning_prompt(
    question: str,
    candidates: list[dict],
    kg_candidates: list[dict] | None = None,
    max_reads: int = 3,
    max_kg_queries: int = 5,
) -> tuple[str, str]:
    paper_lines: list[str] = []
    for i, p in enumerate(candidates[:30], 1):
        has_ft = bool(p.get("has_fulltext") or p.get("full_text"))
        paper_lines.append(f"[{i}] {p.get('title', 'Unknown')}")
        paper_lines.append(f"    doc_id: {p.get('id', '')}")
        paper_lines.append(f"    全文可用: {'是' if has_ft else '否'}")
        summary = p.get("one_line_summary") or (p.get("abstract") or "")[:200]
        if summary:
            paper_lines.append(f"    摘要: {summary}")
        kps = p.get("ai_key_points") or []
        if kps:
            kp_str = "; ".join(str(k)[:60] for k in kps[:3])
            paper_lines.append(f"    要点: {kp_str}")
        paper_lines.append("")
    candidates_context = "\n".join(paper_lines) if paper_lines else "（无候选）"

    kg_lines: list[str] = []
    for ent in (kg_candidates or [])[:30]:
        node_type = ent.get("node_type", "?")
        label = ent.get("label", "")
        deg = ent.get("degree", 0)
        kg_lines.append(f"- [{node_type}] {label}  (degree={deg})")
    kg_candidates_context = "\n".join(kg_lines) if kg_lines else "（KG 还为空或无可用实体）"

    system = PLANNING_SYSTEM_PROMPT.format(
        max_reads=max_reads,
        max_kg_queries=max_kg_queries,
    )
    user = PLANNING_USER_PROMPT.format(
        n_papers=len(candidates[:30]),
        candidates_context=candidates_context,
        n_entities=len(kg_lines),
        kg_candidates_context=kg_candidates_context,
        question=question[:500],
    )
    return system, user


# ╔══════════════════════════════════════════════════════════════════╗
# ║                     Stage 2 — Answering                          ║
# ╚══════════════════════════════════════════════════════════════════╝

RESEARCH_SYSTEM_PROMPT = """你是一位资深科研助手，帮助用户深入分析精选的文献集合。

## 你的能力
1. **回答研究问题** — 基于文献的摘要 / 要点 / 全文节选 + 知识图谱上下文，给有根据的回答
2. **跨论文比较** — 对比不同论文的方法、结论、贡献
3. **识别研究空白** — 找出文献集合中缺失的研究方向
4. **建议后续调查** — 推荐进一步的研究方向或检索策略
5. **维护项目笔记本**（可选）

## 关于「项目笔记本」
- 每个项目一个笔记本，按**主题分成多个 page**（而非一份大杂烩）
- 下方给你看到的 pages 列表里每个 page 有 `page_id / title / 首 200 字预览`
- 你可以决定：**新建一页 / 覆盖某页 / 追加到某页**，或省略
- 值得沉淀：跨论文共识、方法归纳、关键数据表、研究空白、时间线、实验要点
- 不要沉淀琐碎闲聊、重复信息
- 每次最多只做一次 note_update

## 何时 create vs update vs append —— **默认优先 create_page**
- **`create_page` 是首选**：本轮问答若围绕一个清晰主题（如"SAM3 架构细节"、"方法对比"、"数据集评估"），**就新建一页**
- **一页 = 一个主题**，不要往一个"首页 / 合集 / 笔记"大杂烩页里堆东西
- `update_page`：**仅**当新内容是对某既有主题页的**整体重写**（比如信息修正、结构重排）才用，且 page title 必须高度吻合
- `append_to_page`：**仅**当只是在既有主题页末尾打补丁式加一两点才用
- 若既有 pages 里有叫「首页」「新页面」「笔记」这种泛泛标题，**不要往里 append**，给新内容起一个具体主题名，走 create_page
- 省略 note_update：内容不值得沉淀（闲聊、重复、过于零散）

## 回答规则
1. 基于提供的文献和 KG 上下文，不要编造
2. 引用文献用 [1], [2] 编号
3. 中文回答
4. 区分「文献明确提到」与「推测」
5. 文献不足时坦诚说明
6. 若文献附「探针命中的原文节选」，**必须优先引用**这些节选（它们已被精准定位），并在 citations 的 `relevance` 字段说明来自哪个 section
7. 若无探针节选，才退而用 `full_text` / `AI 结构化摘要` / `摘要` 回答
8. 引用原文时可以在 answer 中用 `> "..."` 的 markdown blockquote 直接贴出来
9. 若 `kg_context` 提供邻居实体，可用于跨文献模式识别

## 输出格式（严格 JSON，不要任何额外文字）
```json
{{
  "answer": "详细回答（中文 markdown，含 [N] 引用）",
  "citations": [
    {{"index": 1, "doc_id": "xxx", "relevance": "该文献提供了...的关键证据"}}
  ],
  "follow_up_suggestions": [
    "建议 1：进一步调查...",
    "建议 2：可以检索..."
  ],
  "confidence": 0.85,
  "note_update": {{
    "mode": "create_page",
    "title": "SAM3 架构细节",
    "content": "## 核心革新\\n- ...",
    "reason": "本轮信息足以建立 SAM3 架构的主题页"
  }}
}}
```

note_update 是**可选**字段。各 mode 的必填字段：
- `create_page`：title + content
- `update_page`：page_id + content（title 可选重命名）
- `append_to_page`：page_id + content

若本轮无值得沉淀，**省略 note_update** 字段。

## 关于「文献卡片更新建议」—— card_updates（可选）
若你在精读过程中**明确发现**某篇文献的现有 `one_line_summary / ai_summary / ai_key_points` 存在以下问题，可以给建议：
- **事实错误**：现有摘要与全文节选矛盾
- **关键信息缺失**：现有摘要没覆盖核心贡献
- **过度泛化**：现有一句话总结太空洞，有更具体的版本

不要为了提建议而提：仅当你**有证据**时输出。规则：
1. `doc_id` 必填
2. `field` ∈ {"one_line_summary", "ai_summary", "ai_key_points"}
3. `new_value` 必填（字符串或字符串数组）
4. `reason` 必填：给出证据（引用哪段全文 / 哪条原始数据说明）
5. 本轮最多提 2 个 card_update 建议
6. **不要自动写入**，只是建议——由用户确认

输出格式（附加到顶层 JSON 的 `card_updates` 字段）：
```json
"card_updates": [
  {
    "doc_id": "uuid-xxx",
    "field": "ai_key_points",
    "new_value": ["要点1更新版", "要点2新增"],
    "reason": "原版漏了全文 Results 段报告的 AP=87.3% 关键数据"
  }
]
```

若本轮无合适建议，**省略 card_updates** 字段。"""

RESEARCH_USER_PROMPT = """## 项目描述
{project_description}

## 精选文献（N={n_papers}）
{papers_context}

## 知识图谱上下文
{kg_context}

## 项目笔记本（{n_pages} 个 page）
{pages_section}

## 用户记忆
{memory_section}

## 对话历史
{conversation_history}

## 用户问题
{question}

请基于以上上下文回答用户问题（仅输出 JSON，不要任何前后缀文本）。"""


def _format_kg_context(kg_subgraph: dict | None) -> str:
    if not kg_subgraph:
        return "（本轮未查询 KG 实体）"
    entities = kg_subgraph.get("entities") or []
    if not entities:
        return "（本轮查询的实体未命中 KG）"
    lines: list[str] = []
    for ent in entities[:10]:
        reason = ent.get("reason", "")
        tag = f" — {reason}" if reason else ""
        lines.append(f"- **[{ent.get('node_type','?')}] {ent.get('label','')}**{tag}")
        for nb in (ent.get("neighbors") or [])[:8]:
            lines.append(
                f"    · ({nb.get('edge_type','related')}) → "
                f"[{nb.get('node_type','?')}] {nb.get('label','')}"
            )
    missed = kg_subgraph.get("missed") or []
    if missed:
        lines.append(f"- 未命中的查询：{', '.join(missed[:5])}")
    return "\n".join(lines)


def _format_pages_section(pages: list[dict] | None) -> str:
    if not pages:
        return "（笔记本为空，尚无任何 page）"
    lines: list[str] = []
    for p in pages[:20]:
        pid = p.get("id", "")
        title = (p.get("title") or "未命名")[:100]
        body = (p.get("body_md") or "").strip().replace("\n", " ")
        preview = body[:200]
        lines.append(f"- [page_id: {pid}] **{title}**")
        if preview:
            lines.append(f"  预览: {preview}")
    return "\n".join(lines)


def build_research_prompt(
    question: str,
    papers: list[dict],
    project_description: str,
    user_memory: str = "",
    conversation_history: list[dict] = None,
    pages: list[dict] | None = None,
    kg_subgraph: dict | None = None,
) -> tuple[str, str]:
    paper_lines: list[str] = []
    for i, p in enumerate(papers[:20], 1):
        title = p.get("title", "Unknown")
        summary = p.get("one_line_summary") or (p.get("abstract") or "")[:200]
        authors = (p.get("authors") or "")[:100]
        key_points = p.get("ai_key_points") or []
        kp_str = "; ".join(str(k)[:60] for k in key_points[:3])
        ai_summary = (p.get("ai_summary") or "").strip()
        excerpts = p.get("excerpts") or []   # 探针命中的 section 原文引用
        full_text = p.get("full_text") or ""  # 兜底：无 excerpts 时用整段全文（旧逻辑）

        paper_lines.append(f"[{i}] **{title}**")
        paper_lines.append(f"    doc_id: {p.get('id', '')}")
        if authors:
            paper_lines.append(f"    作者: {authors}")
        if summary:
            paper_lines.append(f"    摘要: {summary}")
        if kp_str:
            paper_lines.append(f"    要点: {kp_str}")
        if ai_summary:
            paper_lines.append(f"    AI 结构化摘要: {ai_summary[:800]}")
        if excerpts:
            paper_lines.append(f"    探针命中的原文节选（共 {len(excerpts)} 段，按相关性降序）:")
            for j, ex in enumerate(excerpts, 1):
                label = ex.get("section_label") or f"段 {ex.get('section_idx', '?')}"
                quote = (ex.get("excerpt_quote") or "").strip()
                insight = (ex.get("insight") or "").strip()
                if not quote:
                    continue
                paper_lines.append(f"      [{i}.{j}] 来自「{label}」(相关性 {ex.get('relevance', 0):.2f})")
                if insight:
                    paper_lines.append(f"            概括: {insight}")
                paper_lines.append(f"            原文: \"{quote}\"")
        elif full_text:
            # 探针未触发（LLM 不可用 / 无全文）时的老兜底
            paper_lines.append(f"    全文节选: {full_text}")
        paper_lines.append("")
    papers_context = "\n".join(paper_lines) if paper_lines else "（暂无文献）"

    memory_section = user_memory[:500] if user_memory else "（无记忆）"

    history_lines: list[str] = []
    if conversation_history:
        for msg in conversation_history[-10:]:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = (msg.get("content") or "")[:200]
            history_lines.append(f"{role}: {content}")
    history_str = "\n".join(history_lines) if history_lines else "（首次提问）"

    pages_list = pages or []
    pages_section = _format_pages_section(pages_list)

    user_prompt = RESEARCH_USER_PROMPT.format(
        project_description=(project_description or "")[:400],
        n_papers=len(papers[:20]),
        papers_context=papers_context,
        kg_context=_format_kg_context(kg_subgraph),
        n_pages=len(pages_list),
        pages_section=pages_section,
        memory_section=memory_section,
        conversation_history=history_str,
        question=question[:500],
    )
    return RESEARCH_SYSTEM_PROMPT, user_prompt
