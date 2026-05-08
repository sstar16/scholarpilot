"""document probe_cache: 跨提问复用的探针原文抽取结果

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-20 18:30:00

动机：
- 协作模式每次提问都对 picks 跑探针 → LLM 成本重复
- 用户在"让 AI 重新分析"里也会跑深度提取 → 这些结果应该沉淀
- probe_cache 每篇存 N 条 (question_hint, excerpts, adopted, created_at)
  下次新问题来时，若命中历史 hint 的概念/关键词 → 直接复用不调 LLM

Schema:
[
  {
    "question_hint": str,        # 原始问题或 hint
    "question_concepts": [str],  # 从 hint 抽取的关键词，命中比对用
    "excerpts": [                # ProbeExcerpt.to_dict() 列表
      {doc_id, section_idx, section_label, char_start, char_end,
       relevance, excerpt_quote, insight, concepts}
    ],
    "adopted": bool,             # 用户采纳用于写入 concepts/methods/results
    "source": "collaboration" | "regenerate",  # 来源
    "created_at": ISO8601 str,
  }
]
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "probe_cache",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "probe_cache")
