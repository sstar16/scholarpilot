import uuid
from sqlalchemy import Integer, Float, Boolean, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class RoundDocument(Base):
    __tablename__ = "round_documents"
    __table_args__ = (UniqueConstraint("round_id", "document_id", name="uq_round_document"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("search_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    rank_in_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    initial_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Scoring Agent fields
    agent_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    one_line_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    below_cutoff: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    round: Mapped["SearchRound"] = relationship("SearchRound", back_populates="round_documents")
    document: Mapped["Document"] = relationship("Document", back_populates="round_documents")
