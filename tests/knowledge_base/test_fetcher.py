import asyncio
import pytest
from pathlib import Path
from backend.app.knowledge_base.fetcher import LocalKBFetcher
from backend.app.knowledge_base.metadata_store import MetadataStore
from backend.app.knowledge_base.search_index import SearchIndex
from backend.app.knowledge_base.relations import RelationStore


@pytest.fixture
def kb_fetcher(tmp_kb_dir, sample_works):
    """构建一个填充了样本数据的 LocalKBFetcher"""
    metadata = MetadataStore(tmp_kb_dir / "metadata.duckdb")
    search = SearchIndex(tmp_kb_dir / "search.sqlite")
    relations = RelationStore(tmp_kb_dir / "relations.sqlite")
    metadata.init_schema()
    search.init_schema()
    relations.init_schema()
    metadata.bulk_insert(sample_works)
    search.bulk_index(sample_works)
    citations = [
        (sample_works[0]["openalex_id"], sample_works[1]["openalex_id"]),
        (sample_works[0]["openalex_id"], sample_works[2]["openalex_id"]),
    ]
    relations.bulk_insert_citations(citations)
    metadata.close()
    search.close()
    relations.close()

    fetcher = LocalKBFetcher(kb_data_dir=tmp_kb_dir)
    yield fetcher
    fetcher.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestLocalKBFetcher:
    def test_source_id(self, kb_fetcher):
        assert kb_fetcher.source_id == "local_kb"

    def test_fetch_returns_results(self, kb_fetcher):
        results = _run(kb_fetcher.fetch("Research Topic", max_results=10))
        assert len(results) > 0

    def test_fetch_result_schema(self, kb_fetcher):
        results = _run(kb_fetcher.fetch("Research Topic", max_results=5))
        doc = results[0]
        assert doc["source"] == "local_kb"
        assert "external_id" in doc
        assert "title" in doc
        assert doc["doc_type"] == "paper"

    def test_fetch_with_year_filter(self, kb_fetcher):
        results = _run(kb_fetcher.fetch("Research", max_results=50, year_from=2024))
        for doc in results:
            pub_date = doc.get("publication_date", "")
            if pub_date:
                assert pub_date >= "2024"

    def test_fetch_no_results(self, kb_fetcher):
        results = _run(kb_fetcher.fetch("xyznonexistentquery123", max_results=10))
        assert len(results) == 0

    def test_fetch_max_results_limit(self, kb_fetcher):
        results = _run(kb_fetcher.fetch("Research", max_results=5))
        assert len(results) <= 5

    def test_is_available(self, kb_fetcher):
        assert kb_fetcher.is_available() is True

    def test_is_not_available_empty_dir(self, tmp_path):
        fetcher = LocalKBFetcher(kb_data_dir=tmp_path / "nonexistent")
        assert fetcher.is_available() is False
