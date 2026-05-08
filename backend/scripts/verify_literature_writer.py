"""
Verify LiteratureWriter.persist end-to-end in a throwaway sandbox.

Usage:
    docker exec scholarpilot-dev-backend-1 python -m scripts.verify_literature_writer
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from app.services.literature_writer import LiteratureWriter, make_slug, parse_frontmatter
from app.harness.file_tools.registry import tool_registry


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["PROJECT_WORKSPACE_DIR"] = tmpdir
        project_id = "test-project-abc"

        writer = LiteratureWriter(project_id, tool_registry())

        doc = {
            "id": "00000000-1111-2222-3333-444444444444",
            "title": "Attention Is All You Need",
            "title_zh": "注意力即一切",
            "authors": ["Vaswani", "Shazeer", "Parmar"],
            "source": "openalex",
            "external_id": "W123456789",
            "doi": "10.1234/xyz",
            "publication_date": "2017-06-12",
            "journal": "NeurIPS",
            "url": "https://example.com/paper",
            "pdf_url": "https://example.com/paper.pdf",
            "abstract": "We propose a new architecture called Transformer.",
            "round_id": "round-uuid-1",
        }
        llm_result = {
            "summary": "这篇论文提出了 Transformer 架构,用纯注意力机制替代 RNN。",
            "key_points": ["提出 Transformer", "多头注意力", "SOTA in WMT'14"],
            "one_line_summary": "用纯注意力替代 RNN 的开山之作",
            "quality_score": 0.95,
            "concepts": [
                {"name": "Transformer", "type": "method", "confidence": 0.98},
                {"name": "Self-Attention", "type": "concept", "confidence": 0.95},
            ],
            "methods": [
                {"name": "Multi-Head Attention", "short": "并行多头注意力"},
            ],
            "results": [
                {"claim": "WMT'14 英德 28.4 BLEU SOTA", "evidence": "Table 2"},
            ],
            "citations_mentioned": ["Bahdanau et al. 2014"],
        }

        slug = await writer.persist(doc, "very_relevant", llm_result)
        print(f"OK persisted slug={slug}")

        # Read back
        md_path = Path(tmpdir) / project_id / "literature" / f"{slug}.md"
        assert md_path.exists(), f"file not created: {md_path}"
        text = md_path.read_text(encoding="utf-8")
        print(f"OK file exists, {len(text)} bytes")

        fm, body = parse_frontmatter(text)
        assert fm["bucket"] == "very_relevant"
        assert fm["year"] == 2017
        assert len(fm["concepts"]) == 2
        assert fm["concepts"][0]["name"] == "Transformer"
        assert "Multi-Head Attention" in body
        assert "WMT'14 英德 28.4 BLEU" in body
        print("OK frontmatter and body match expectations")

        print("\n--- Preview first 40 lines ---")
        print("\n".join(text.splitlines()[:40]))

        # --- Second doc, then rebuild_index ---
        doc2 = dict(doc)
        doc2["id"] = "11111111-2222-3333-4444-555555555555"
        doc2["title"] = "BERT Pre-training"
        doc2["publication_date"] = "2019-05-24"
        llm2 = dict(llm_result)
        llm2["summary"] = "BERT 通过双向 masked LM 预训练。"
        await writer.persist(doc2, "relevant", llm2)

        await writer.rebuild_index()
        print("\nOK rebuild_index called")

        index_path = Path(tmpdir) / project_id / "literature" / "_index.md"
        assert index_path.exists()
        index_text = index_path.read_text(encoding="utf-8")
        assert "## Very Relevant" in index_text
        assert "## Relevant" in index_text
        assert "[[attention-is-all-you-need_" in index_text
        assert "[[bert-pre-training_" in index_text
        print("OK _index.md contains both entries with wiki links")

        slug_map_path = Path(tmpdir) / project_id / "literature" / ".metadata" / "slug_map.json"
        assert slug_map_path.exists()
        import json as json_mod
        slug_map = json_mod.loads(slug_map_path.read_text(encoding="utf-8"))
        assert len(slug_map["entries"]) == 2
        print(f"OK slug_map.json has {len(slug_map['entries'])} entries")

        # --- update_bucket ---
        ok = await writer.update_bucket(doc["id"], "relevant")
        assert ok, "update_bucket should have succeeded"

        slug = make_slug(doc["id"], doc["title"])
        md_text = (Path(tmpdir) / project_id / "literature" / f"{slug}.md").read_text("utf-8")
        fm, _ = parse_frontmatter(md_text)
        assert fm["bucket"] == "relevant", f"bucket not updated: {fm['bucket']}"
        print(f"OK update_bucket(): frontmatter.bucket = {fm['bucket']}")

        # Missing doc
        ok = await writer.update_bucket("99999999-0000-0000-0000-000000000000", "very_relevant")
        assert ok is False, "update_bucket should return False for unknown doc"
        print("OK update_bucket() returns False for unknown doc_id")


if __name__ == "__main__":
    asyncio.run(main())
