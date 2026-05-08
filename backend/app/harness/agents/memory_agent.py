"""
Memory Update Agent — 从用户反馈的 4-bucket 文档中学习研究偏好。
替代纯关键词频率的 profile 更新，用 LLM 理解用户真正想要什么。

与现有 profile_service.update_profile_from_feedbacks() 并行运行，互为冗余。

P0.5（2026-05-06）：返回值升级为 MemoryUpdateResult — 既给 backend DB 写单段 markdown
（兼容 web frontend），也给 client 写多 .md 文件（学 Claude Code MEMORY.md 索引模式）。
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict

from app.harness.prompts.memory_update import build_memory_update_prompt

logger = logging.getLogger(__name__)


class MemoryFileSpec(TypedDict):
    """单个 memory 文件规格 —— 客户端写本地时用作 frontmatter + body 来源。"""
    filename: str       # e.g. "research_focus.md"，必须以 .md 结尾，不含路径
    type: str           # identity / preference / reference / note
    name: str           # 人类可读名（MEMORY.md 索引展示）
    description: str    # 一句话描述（索引展示）
    body: str           # markdown 正文，不含 frontmatter（client 写时由 memoryRepo 加）


@dataclass
class MemoryUpdateResult:
    """MemoryAgent 输出。markdown 字段写 backend DB（兼容 web）；files + focus 给客户端写本地。

    index_md：backend 给的"快照式"索引，仅含本次 LLM 输出的 files；client 端会用 rebuildMemoryIndex
    重新生成（含本地历史 file），所以 client 实际不依赖此字段。保留是给纯 web/curl 调用方对照。
    """
    markdown: str
    files: List[MemoryFileSpec]
    index_md: str
    version: int
    focus: str          # 一句话研究方向，索引头部 "_当前研究方向：X_" 用


class MemoryAgent:
    """
    LLM-driven user memory updater.
    Takes 4-bucket feedback and produces structured memory text.
    """

    def __init__(self, llm_manager=None):
        self._llm = llm_manager

    async def update_memory(
        self,
        project_description: str,
        current_memory: str,
        memory_version: int,
        feedback_buckets: Dict[int, List[Dict]],
    ) -> Optional[MemoryUpdateResult]:
        """
        根据反馈更新记忆。

        Args:
            project_description: 项目描述
            current_memory: 当前 memory_text（可能为空）
            memory_version: 当前版本号
            feedback_buckets: {2: [...], 1: [...], 0: [...], -1: [...]}

        Returns:
            MemoryUpdateResult（markdown + files + index_md + version），或 None（LLM 不可用 / 无反馈 / 失败）
        """
        if not self._llm:
            logger.warning("[MemoryAgent] LLM 不可用，跳过记忆更新")
            return None

        total_feedback = sum(len(v) for v in feedback_buckets.values())
        if total_feedback == 0:
            return None

        prompt = build_memory_update_prompt(
            project_description=project_description,
            current_memory=current_memory,
            memory_version=memory_version,
            feedback_buckets=feedback_buckets,
        )

        try:
            result = await self._llm.generate(
                prompt, temperature=0.2,
                response_format={"type": "json_object"},
            )
            if not result:
                logger.warning("[MemoryAgent] LLM 返回空结果")
                return None

            parsed = _parse_memory_response(result)
            if not parsed:
                logger.warning("[MemoryAgent] 解析失败: %s", result[:200])
                return None

            new_version = memory_version + 1
            memory_text = _format_memory_markdown(parsed, new_version)
            focus = (parsed.get("research_focus") or "").strip()

            # v4: LLM 直接输出 files 列表；v3 fallback: 程序拍固定 7 类
            if "files" in parsed and isinstance(parsed.get("files"), list):
                files = _files_from_llm_response(parsed)
                if not files:
                    files = _files_from_parsed(parsed)
            else:
                files = _files_from_parsed(parsed)

            index_md = _format_index_md(files, new_version, focus)

            logger.info(
                "[MemoryAgent] 记忆更新成功 v%d → v%d, focus: %s, files: %d",
                memory_version, new_version, focus[:50], len(files),
            )
            return MemoryUpdateResult(
                markdown=memory_text,
                files=files,
                index_md=index_md,
                version=new_version,
                focus=focus,
            )

        except Exception as e:
            logger.warning("[MemoryAgent] 记忆更新异常: %s", e)
            return None


async def run_memory_update(
    user_id,
    project_id,
    project_description: str,
    feedback_dicts: List[Dict],
    llm_manager,
    db,
) -> Optional[MemoryUpdateResult]:
    """
    便捷入口：从 feedback list 构建 4-bucket 并运行 MemoryAgent。
    直接更新 DB 和 Redis；返回 MemoryUpdateResult 给 feedback API → client 写本地多文件。
    """
    from app.models.user_profile import UserProfile
    from sqlalchemy import select

    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_id,
            UserProfile.project_id == project_id,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return None

    buckets: Dict[int, List[Dict]] = {2: [], 1: [], 0: [], -1: []}
    for fd in feedback_dicts:
        rel = fd.get("relevance", 0)
        if rel in buckets:
            buckets[rel].append({
                "title": fd.get("title", ""),
                "one_line_summary": fd.get("one_line_summary", ""),
                "source": fd.get("source", ""),
            })

    agent = MemoryAgent(llm_manager=llm_manager)
    update_result = await agent.update_memory(
        project_description=project_description,
        current_memory=profile.memory_text or "",
        memory_version=profile.memory_version or 0,
        feedback_buckets=buckets,
    )
    if not update_result:
        return None

    profile.memory_text = update_result.markdown
    profile.memory_version = update_result.version
    await db.flush()

    try:
        import redis.asyncio as aioredis
        from app.config import settings
        r = aioredis.from_url(settings.redis_url)
        await r.set(
            f"memory:{user_id}:{project_id}",
            update_result.markdown,
            ex=86400,
        )
        await r.close()
    except Exception as e:
        logger.warning("[MemoryAgent] Redis 缓存失败: %s", e)

    return update_result


def _parse_memory_response(text: str) -> Optional[Dict]:
    """从 LLM 输出解析记忆 JSON，同时支持 v4（files 字段）和 v3（顶层字段）。"""
    # 提取最外层 JSON 对象（贪婪匹配，支持嵌套）
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        # 尝试逐步缩短找到有效 JSON（处理尾部垃圾）
        raw = match.group()
        for end in range(len(raw), 0, -1):
            try:
                data = json.loads(raw[:end])
                break
            except json.JSONDecodeError:
                continue
        else:
            return None

    # v4：有 files 列表
    if "files" in data and isinstance(data.get("files"), list):
        if "research_focus" not in data:
            return None
        return data

    # v3 fallback：顶层 research_focus
    if "research_focus" in data:
        return data

    return None


def _files_from_llm_response(parsed: Dict) -> List[MemoryFileSpec]:
    """v4 路径：直接用 LLM 给出的 files 列表，做基本校验和清洗。"""
    raw_files = parsed.get("files") or []
    files: List[MemoryFileSpec] = []
    seen_filenames: set = set()

    for item in raw_files:
        if not isinstance(item, dict):
            continue
        filename = (item.get("filename") or "").strip()
        # 强制 snake_case.md，防注入
        if not filename or not re.match(r'^[a-z0-9_]+\.md$', filename):
            continue
        if filename in seen_filenames:
            continue
        seen_filenames.add(filename)

        ftype = item.get("type", "note")
        if ftype not in ("identity", "preference", "reference", "note"):
            ftype = "note"

        name = (item.get("name") or filename.replace("_", " ").replace(".md", "")).strip()
        description = _truncate((item.get("description") or "").strip(), 60)
        body = (item.get("body") or "").strip()

        if not body:
            continue

        files.append({
            "filename": filename,
            "type": ftype,
            "name": name,
            "description": description,
            "body": body,
        })

    return files


def _files_from_parsed(parsed: Dict) -> List[MemoryFileSpec]:
    """把 LLM 输出的 v3 dict 拍成多 MemoryFileSpec（仅含非空字段对应的文件）。

    P0.5 阶段方案：固定 7 类 .md 文件名映射；后续可升 LLM 自由输出 files。
    """
    files: List[MemoryFileSpec] = []

    focus = (parsed.get("research_focus") or "").strip()
    if focus:
        files.append({
            "filename": "research_focus.md",
            "type": "identity",
            "name": "研究方向",
            "description": _truncate(focus, 60),
            "body": focus,
        })

    pref = parsed.get("preferred_topics") or []
    if pref:
        files.append({
            "filename": "preferred_topics.md",
            "type": "preference",
            "name": "偏好主题",
            "description": f"{len(pref)} 个用户关注的主题",
            "body": "\n".join(f"- {t}" for t in pref if t),
        })

    excl = parsed.get("excluded_topics") or []
    if excl:
        files.append({
            "filename": "excluded_topics.md",
            "type": "preference",
            "name": "排除主题",
            "description": f"{len(excl)} 个不感兴趣的方向",
            "body": "\n".join(f"- {t}" for t in excl if t),
        })

    methods = parsed.get("methodology_preferences") or []
    if methods:
        files.append({
            "filename": "methodology.md",
            "type": "preference",
            "name": "方法偏好",
            "description": f"{len(methods)} 个偏好的研究方法",
            "body": "\n".join(f"- {m}" for m in methods if m),
        })

    authors = parsed.get("key_authors") or []
    if authors:
        files.append({
            "filename": "authors.md",
            "type": "reference",
            "name": "关键作者",
            "description": f"{len(authors)} 个重要作者",
            "body": "\n".join(f"- {a}" for a in authors if a),
        })

    sources = parsed.get("source_preferences") or []
    if sources:
        files.append({
            "filename": "sources.md",
            "type": "preference",
            "name": "来源偏好",
            "description": f"{len(sources)} 个偏好的数据源",
            "body": "\n".join(f"- {s}" for s in sources if s),
        })

    notes = (parsed.get("notes") or "").strip()
    if notes:
        files.append({
            "filename": "notes.md",
            "type": "note",
            "name": "补充说明",
            "description": _truncate(notes, 60),
            "body": notes,
        })

    return files


def _format_index_md(files: List[MemoryFileSpec], version: int, focus: str) -> str:
    """生成 MEMORY.md 索引（学 Claude Code 的索引格式）。"""
    lines = [
        f"# 项目记忆 v{version}",
        "",
        "> AI 自动维护；编辑请直接打开本目录下的 .md 文件",
        "",
    ]
    if focus:
        lines.append(f"_当前研究方向：{focus}_")
        lines.append("")

    if not files:
        lines.append("_暂无记忆条目_")
    else:
        for f in files:
            lines.append(f"- [{f['name']}]({f['filename']}) — {f['description']}")

    lines.append("")
    return "\n".join(lines)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _format_memory_markdown(data: Dict, version: int) -> str:
    """将解析后的 JSON 转为可读的 markdown 记忆文本"""
    lines = [f"# 研究偏好记忆 v{version}", ""]

    focus = data.get("research_focus", "")
    if focus:
        lines.append(f"## 核心方向\n{focus}\n")

    preferred = data.get("preferred_topics", [])
    if preferred:
        lines.append("## 偏好主题")
        for t in preferred:
            lines.append(f"- {t}")
        lines.append("")

    excluded = data.get("excluded_topics", [])
    if excluded:
        lines.append("## 排除方向")
        for t in excluded:
            lines.append(f"- {t}")
        lines.append("")

    methods = data.get("methodology_preferences", [])
    if methods:
        lines.append("## 方法偏好")
        for m in methods:
            lines.append(f"- {m}")
        lines.append("")

    authors = data.get("key_authors", [])
    if authors:
        lines.append("## 关键作者")
        for a in authors:
            lines.append(f"- {a}")
        lines.append("")

    sources = data.get("source_preferences", [])
    if sources:
        lines.append("## 来源偏好")
        for s in sources:
            lines.append(f"- {s}")
        lines.append("")

    notes = data.get("notes", "")
    if notes:
        lines.append(f"## 备注\n{notes}\n")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Phase 3.2: Structured memory enrichment from bucket signals
# ------------------------------------------------------------------

async def enrich_from_bucket_signals(
    user_id,
    project_id,
    db,
):
    """
    从 4 桶分类信号中提取结构化记忆。
    汇聚 very_relevant 的正面信号和 irrelevant 的负面信号。
    结果存入 UserProfile.structured_memory (JSON)。
    """
    from app.models.user_profile import UserProfile
    from app.models.document import Document
    from app.models.document_classification import DocumentClassification
    from sqlalchemy import select, func

    # Fetch profile
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_id,
            UserProfile.project_id == project_id,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return

    # Aggregate signals from classified documents
    structured = {
        "positive_topics": [],
        "positive_authors": [],
        "positive_journals": [],
        "negative_signals": [],
        "bucket_counts": {},
    }

    for bucket in ("very_relevant", "relevant", "uncertain", "irrelevant"):
        docs_result = await db.execute(
            select(Document)
            .join(DocumentClassification, DocumentClassification.document_id == Document.id)
            .where(
                DocumentClassification.project_id == project_id,
                DocumentClassification.user_id == user_id,
                DocumentClassification.bucket == bucket,
            )
        )
        docs = docs_result.scalars().all()
        structured["bucket_counts"][bucket] = len(docs)

        for doc in docs:
            if bucket in ("very_relevant", "relevant"):
                # Positive signals
                if doc.journal:
                    structured["positive_journals"].append(doc.journal)
                if doc.authors:
                    for a in doc.authors.split(";")[:3]:
                        a = a.strip()
                        if a:
                            structured["positive_authors"].append(a)
                if doc.ai_key_points:
                    for kp in doc.ai_key_points[:2]:
                        if kp:
                            structured["positive_topics"].append(str(kp)[:80])
            elif bucket == "irrelevant":
                if doc.one_line_summary:
                    structured["negative_signals"].append(doc.one_line_summary[:100])

    # Deduplicate and limit
    structured["positive_topics"] = list(dict.fromkeys(structured["positive_topics"]))[:20]
    structured["positive_authors"] = list(dict.fromkeys(structured["positive_authors"]))[:15]
    structured["positive_journals"] = list(dict.fromkeys(structured["positive_journals"]))[:10]
    structured["negative_signals"] = list(dict.fromkeys(structured["negative_signals"]))[:10]

    profile.structured_memory = structured
    await db.flush()

    logger.info(
        "[MemoryAgent] Enriched structured memory for project=%s: +topics=%d, +authors=%d, -signals=%d",
        str(project_id)[:8],
        len(structured["positive_topics"]),
        len(structured["positive_authors"]),
        len(structured["negative_signals"]),
    )
