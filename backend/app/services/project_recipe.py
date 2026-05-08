"""Project recipe — 4 桶反馈完成后纯统计 regenerate 的项目级 markdown。

设计原则：
- **零 LLM**：纯统计 + 模板拼接，确定性输出。每次跑同样的 input 出同样的 markdown。
- **零侵入**：消费方一处即可（``markdown_memory.build_combined_memory_for_agents``
  追加 auto_recipe_md），所有 agent 自动拿到。
- **快**：单 project 通常 50-200 条 classification + 1000 条以下 concept_tags，
  整个 regenerate 应该 <100ms。

公开入口：
    await regenerate_project_recipe(project_id=..., db=...)

返回 (markdown, RecipeStats)。Side effect：UserProfile.auto_recipe_md /
recipe_updated_at 落库。
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


_BUCKET_ORDER = ("very_relevant", "relevant", "uncertain", "irrelevant")
_BUCKET_LABELS = {
    "very_relevant": "very_relevant",
    "relevant": "relevant",
    "uncertain": "uncertain",
    "irrelevant": "irrelevant",
}
_TOP_KEYWORDS_AFFINITY = 8
_TOP_KEYWORDS_AVERSION = 6
_TOP_THEMES = 10
_TOP_SOURCES = 10


@dataclass
class RecipeStats:
    bucket_counts: dict[str, int] = field(default_factory=dict)
    total_classified: int = 0
    source_hit: list[dict] = field(default_factory=list)
    affinity_keywords: list[tuple[str, int]] = field(default_factory=list)
    aversion_keywords: list[tuple[str, int]] = field(default_factory=list)
    themes: list[tuple[str, int]] = field(default_factory=list)


def _SearchRound():  # noqa: N802 — lazy model resolution (avoid asyncpg at import)
    from app.models.search_round import SearchRound
    return SearchRound


def _Document():  # noqa: N802
    from app.models.document import Document
    return Document


def _DocClass():  # noqa: N802
    from app.models.document_classification import DocumentClassification
    return DocumentClassification


def _UserProfile():  # noqa: N802
    from app.models.user_profile import UserProfile
    return UserProfile


# ── Compute helpers (each isolated; testable with FakeDB) ──────────────────


async def compute_bucket_distribution(
    project_id: uuid.UUID, db: AsyncSession,
) -> tuple[dict[str, int], int]:
    """Returns ({bucket: count}, total_classified)."""
    DocClass = _DocClass()
    res = await db.execute(
        select(DocClass.bucket, func.count())
        .where(DocClass.project_id == project_id)
        .group_by(DocClass.bucket)
    )
    counts: dict[str, int] = {b: 0 for b in _BUCKET_ORDER}
    for row in res.all():
        bucket, n = row[0], row[1]
        if bucket in counts:
            counts[bucket] = int(n)
    total = sum(counts.values())
    return counts, total


async def compute_source_hit_rate(
    project_id: uuid.UUID, db: AsyncSession,
) -> list[dict]:
    """Per-source: {source, very_rel, relevant_total, total, hit_rate}.
    Sorted by very_rel desc, hit_rate desc."""
    Document = _Document()
    DocClass = _DocClass()

    # very_relevant counts by source
    vr_q = await db.execute(
        select(Document.source, func.count())
        .join(DocClass, DocClass.document_id == Document.id)
        .where(
            DocClass.project_id == project_id,
            DocClass.bucket == "very_relevant",
        )
        .group_by(Document.source)
    )
    very_rel_counts = {row[0]: int(row[1]) for row in vr_q.all() if row[0]}

    # total classified counts by source
    total_q = await db.execute(
        select(Document.source, func.count())
        .join(DocClass, DocClass.document_id == Document.id)
        .where(DocClass.project_id == project_id)
        .group_by(Document.source)
    )
    total_counts = {row[0]: int(row[1]) for row in total_q.all() if row[0]}

    rows: list[dict] = []
    for source, total in total_counts.items():
        vr = very_rel_counts.get(source, 0)
        hit_rate = vr / total if total else 0.0
        rows.append({
            "source": source,
            "very_rel": vr,
            "total": total,
            "hit_rate": hit_rate,
        })
    rows.sort(key=lambda r: (r["very_rel"], r["hit_rate"]), reverse=True)
    return rows[:_TOP_SOURCES]


async def compute_keyword_signals(
    project_id: uuid.UUID, db: AsyncSession,
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Aggregate concept_tags across very_relevant docs (affinity) vs
    irrelevant docs (aversion). Returns (top_affinity, top_aversion)."""
    Document = _Document()
    DocClass = _DocClass()

    res = await db.execute(
        select(Document.concept_tags, DocClass.bucket)
        .join(DocClass, DocClass.document_id == Document.id)
        .where(
            DocClass.project_id == project_id,
            DocClass.bucket.in_(("very_relevant", "irrelevant")),
            Document.concept_tags.isnot(None),
        )
    )
    affinity_counter: Counter[str] = Counter()
    aversion_counter: Counter[str] = Counter()
    for row in res.all():
        tags, bucket = row[0] or [], row[1]
        target = affinity_counter if bucket == "very_relevant" else aversion_counter
        for t in tags:
            if t and isinstance(t, str):
                target[t.strip().lower()] += 1

    # Remove tags that show up significantly in BOTH (noise like generic terms)
    for tag in list(affinity_counter):
        if aversion_counter.get(tag, 0) >= max(2, affinity_counter[tag] // 2):
            affinity_counter.pop(tag, None)
            aversion_counter.pop(tag, None)
    affinity = affinity_counter.most_common(_TOP_KEYWORDS_AFFINITY)
    aversion = aversion_counter.most_common(_TOP_KEYWORDS_AVERSION)
    return affinity, aversion


async def compute_themes(
    project_id: uuid.UUID, db: AsyncSession,
) -> list[tuple[str, int]]:
    """Top concept_tags across the entire library — gives agents a coarse
    sense of the user's literature universe."""
    Document = _Document()
    DocClass = _DocClass()

    res = await db.execute(
        select(Document.concept_tags)
        .join(DocClass, DocClass.document_id == Document.id)
        .where(
            DocClass.project_id == project_id,
            Document.concept_tags.isnot(None),
        )
    )
    counter: Counter[str] = Counter()
    for row in res.all():
        for t in row[0] or []:
            if t and isinstance(t, str):
                counter[t.strip().lower()] += 1
    return counter.most_common(_TOP_THEMES)


# ── Markdown formatting (pure, easily unit-tested) ─────────────────────────


def format_recipe_markdown(stats: RecipeStats, *, now: Optional[datetime] = None) -> str:
    """Render the stats bundle as a deterministic markdown string."""
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        f"# 项目食谱（自动生成 · {ts}）",
        "",
        "> 基于 4 桶反馈与文献库统计自动归纳。要修改下面的偏好，请编辑用户记忆或项目记忆。",
        "",
    ]

    lines += _format_bucket_section(stats)
    lines += _format_source_section(stats)
    lines += _format_keyword_section(stats)
    lines += _format_themes_section(stats)
    lines += _format_directive_section(stats)
    return "\n".join(lines).rstrip() + "\n"


def _format_bucket_section(stats: RecipeStats) -> list[str]:
    out = ["## 一、4 桶分布"]
    if stats.total_classified == 0:
        out.append("- 还没有任何分类反馈。")
        out.append("")
        return out
    for b in _BUCKET_ORDER:
        n = stats.bucket_counts.get(b, 0)
        pct = (n / stats.total_classified * 100) if stats.total_classified else 0
        out.append(f"- {_BUCKET_LABELS[b]}: {n} 篇 ({pct:.0f}%)")
    out.append(f"- 已分类总数：{stats.total_classified} 篇")
    out.append("")
    return out


def _format_source_section(stats: RecipeStats) -> list[str]:
    out = ["## 二、来源命中率（按 very_relevant 排序）"]
    if not stats.source_hit:
        out.append("- 暂无数据。")
        out.append("")
        return out
    out += ["| 来源 | very_rel/总 | 命中率 |", "|---|---|---|"]
    for r in stats.source_hit:
        out.append(f"| {r['source']} | {r['very_rel']}/{r['total']} | {r['hit_rate']*100:.0f}% |")
    out.append("")
    return out


def _format_keyword_section(stats: RecipeStats) -> list[str]:
    out = ["## 三、关键词信号"]
    if stats.affinity_keywords:
        out.append("**亲和**（出现在 very_relevant 桶的高频概念）：")
        for kw, n in stats.affinity_keywords:
            out.append(f"- {kw} ({n} 次)")
    else:
        out.append("**亲和**：尚无足够 very_relevant 数据。")
    out.append("")
    if stats.aversion_keywords:
        out.append("**排斥**（出现在 irrelevant 桶的高频概念）：")
        for kw, n in stats.aversion_keywords:
            out.append(f"- {kw} ({n} 次)")
    else:
        out.append("**排斥**：暂无明显排斥模式。")
    out.append("")
    return out


def _format_themes_section(stats: RecipeStats) -> list[str]:
    out = ["## 四、文献库主题（高频概念标签）"]
    if not stats.themes:
        out.append("- 暂无 concept_tags 数据。")
    else:
        for tag, n in stats.themes:
            out.append(f"- {tag} · {n}")
    out.append("")
    return out


def _format_directive_section(stats: RecipeStats) -> list[str]:
    out = ["## 五、给下游 agent 的指引"]
    if stats.source_hit:
        top_sources = [r["source"] for r in stats.source_hit[:3] if r["very_rel"] > 0]
        if top_sources:
            out.append(
                f"- **ScoringAgent / QueryPlanAgent**：优先信任来源 "
                f"{', '.join(top_sources)}。"
            )
    if stats.affinity_keywords:
        kws = [k for k, _ in stats.affinity_keywords[:5]]
        out.append(f"- **QueryPlanAgent**：扩展词优先选 {', '.join(kws)}。")
    if stats.aversion_keywords:
        kws = [k for k, _ in stats.aversion_keywords[:5]]
        out.append(f"- **QueryPlanAgent**：避开 {', '.join(kws)}。")
    if stats.bucket_counts.get("very_relevant", 0) > 0:
        out.append("- **ResearchAgent（协作模式）**：优先引用 very_relevant 桶的文献。")
    if not (stats.source_hit or stats.affinity_keywords or stats.aversion_keywords):
        out.append("- 反馈样本不足，下游 agent 走默认策略。")
    out.append("")
    return out


# ── Main orchestrator ──────────────────────────────────────────────────────


async def regenerate_project_recipe(
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    now: Optional[datetime] = None,
    commit: bool = True,
) -> tuple[str, RecipeStats]:
    """Compute all stats, render markdown, persist on UserProfile.
    Returns (markdown, stats) for inspection / testing."""
    bucket_counts, total = await compute_bucket_distribution(project_id, db)
    source_hit = await compute_source_hit_rate(project_id, db)
    affinity, aversion = await compute_keyword_signals(project_id, db)
    themes = await compute_themes(project_id, db)

    stats = RecipeStats(
        bucket_counts=bucket_counts,
        total_classified=total,
        source_hit=source_hit,
        affinity_keywords=affinity,
        aversion_keywords=aversion,
        themes=themes,
    )
    md = format_recipe_markdown(stats, now=now)

    UserProfile = _UserProfile()
    now_utc = now or datetime.now(timezone.utc)
    await db.execute(
        update(UserProfile)
        .where(
            UserProfile.user_id == user_id,
            UserProfile.project_id == project_id,
        )
        .values(auto_recipe_md=md, recipe_updated_at=now_utc)
    )
    if commit:
        await db.commit()
    logger.info(
        "[ProjectRecipe] regenerated for project=%s — total=%d, sources=%d, "
        "aff=%d, av=%d, themes=%d",
        str(project_id)[:8],
        total, len(source_hit),
        len(affinity), len(aversion), len(themes),
    )
    return md, stats
