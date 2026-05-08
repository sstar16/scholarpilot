"""
Tests for SearchIndex (SQLite FTS5 + jieba)
"""
import pytest
from pathlib import Path

from backend.app.knowledge_base.search_index import SearchIndex


@pytest.fixture
def index(tmp_kb_dir):
    """初始化好 schema 的 SearchIndex 实例，测试后关闭。"""
    idx = SearchIndex(tmp_kb_dir / "search.sqlite")
    idx.init_schema()
    yield idx
    idx.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_create_schema(tmp_kb_dir):
    """init_schema 应正常创建 FTS5 表和 works_meta 表。"""
    idx = SearchIndex(tmp_kb_dir / "search.sqlite")
    idx.init_schema()
    # 验证两张表存在
    conn = idx._get_conn()
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow')"
    ).fetchall()}
    assert "works_meta" in tables
    idx.close()


# ---------------------------------------------------------------------------
# Bulk index
# ---------------------------------------------------------------------------

def test_bulk_index(index, sample_works):
    """插入 100 条后 count() == 100。"""
    index.bulk_index(sample_works)
    assert index.count() == 100


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_english(index, sample_works):
    """搜索英文词 'Research Topic' 应返回含 openalex_id 和 bm25_score 的结果。"""
    index.bulk_index(sample_works)
    results = index.search("Research Topic")
    assert len(results) > 0
    first = results[0]
    assert "openalex_id" in first
    assert "bm25_score" in first


def test_search_returns_ranked(index, sample_works):
    """结果应按 bm25_score 升序排列（FTS5 bm25() 返回负数，越小越相关）。"""
    index.bulk_index(sample_works)
    results = index.search("Research Topic", limit=50)
    assert len(results) > 1
    scores = [r["bm25_score"] for r in results]
    assert scores == sorted(scores)


def test_search_no_results(index, sample_works):
    """搜索不存在的词应返回空列表。"""
    index.bulk_index(sample_works)
    results = index.search("xyzzy_nonexistent_term_12345")
    assert results == []


def test_search_with_year_filter(index, sample_works):
    """year_from=2024 过滤后，所有结果的 publication_year >= 2024。"""
    index.bulk_index(sample_works)
    results = index.search("Research", year_from=2024)
    assert len(results) > 0
    for r in results:
        assert r["publication_year"] >= 2024


def test_search_chinese_segmented(index):
    """中文标题经 jieba 分词后，搜索子词应能命中。"""
    doc = {
        "openalex_id": "W9999999",
        "title": "深度学习在自然语言处理中的应用",
        "abstract_preview": None,
        "authors": "张三",
        "source_name": "计算机学报",
        "publication_year": 2023,
    }
    index.bulk_index([doc])
    assert index.count() == 1

    results = index.search("深度学习 自然语言")
    assert len(results) == 1
    assert results[0]["openalex_id"] == "W9999999"
