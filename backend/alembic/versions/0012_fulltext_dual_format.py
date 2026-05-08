"""fulltext dual format (pdf + html) columns

让一篇文献的 PDF 和 HTML 两种形式可以共存：之前下过 PDF 的也可以再下 HTML,
之前下过 HTML 的也可以再下 PDF, 互不覆盖。

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 新增 4 个字段，默认 not_attempted / NULL
    op.add_column(
        "documents",
        sa.Column("fulltext_pdf_path", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "fulltext_pdf_status",
            sa.String(length=30),
            server_default="not_attempted",
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("fulltext_html_path", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "fulltext_html_status",
            sa.String(length=30),
            server_default="not_attempted",
            nullable=False,
        ),
    )

    # Backfill: 根据旧 fulltext_path 后缀把已有下载迁移到对应新字段
    # .pdf → pdf 通道
    op.execute(
        """
        UPDATE documents
           SET fulltext_pdf_path = fulltext_path,
               fulltext_pdf_status = 'available'
         WHERE fulltext_status = 'available'
           AND fulltext_path ILIKE '%.pdf'
        """
    )
    # .html / .htm → html 通道
    op.execute(
        """
        UPDATE documents
           SET fulltext_html_path = fulltext_path,
               fulltext_html_status = 'available'
         WHERE fulltext_status = 'available'
           AND (fulltext_path ILIKE '%.html' OR fulltext_path ILIKE '%.htm')
        """
    )
    # failed 状态继承（两个通道都标 failed）
    op.execute(
        """
        UPDATE documents
           SET fulltext_pdf_status = 'failed',
               fulltext_html_status = 'failed'
         WHERE fulltext_status = 'failed'
        """
    )
    # downloading 状态也继承（兼容正在进行中的任务）
    op.execute(
        """
        UPDATE documents
           SET fulltext_pdf_status = 'downloading'
         WHERE fulltext_status = 'downloading'
        """
    )


def downgrade() -> None:
    op.drop_column("documents", "fulltext_html_status")
    op.drop_column("documents", "fulltext_html_path")
    op.drop_column("documents", "fulltext_pdf_status")
    op.drop_column("documents", "fulltext_pdf_path")
