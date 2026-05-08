import pytest


@pytest.fixture
def tmp_kb_dir(tmp_path):
    """临时 KB 数据目录"""
    return tmp_path


@pytest.fixture
def sample_works():
    """100 条模拟 OpenAlex work 记录"""
    works = []
    for i in range(100):
        works.append({
            "openalex_id": f"W{1000000 + i}",
            "doi": f"10.1234/test.{i}" if i % 3 != 0 else None,
            "title": f"Research on Topic {i}: A {'Chinese' if i % 5 == 0 else 'Global'} Perspective",
            "publication_year": 2020 + (i % 6),
            "publication_date": f"{2020 + (i % 6)}-{(i % 12) + 1:02d}-15",
            "language": "zh" if i % 5 == 0 else "en",
            "type": "article",
            "cited_by_count": i * 10,
            "authors": f"Author A{i}; Author B{i}",
            "source_name": f"Journal of Testing {i % 10}",
            "source_issn": f"1234-{i % 10:04d}",
            "abstract_preview": f"This paper investigates topic {i} using novel methods. " * 5 if i % 4 != 0 else None,
            "primary_topic_id": f"T{i % 20}",
            "primary_topic_name": f"Topic Area {i % 20}",
            "primary_field_name": f"Field {i % 5}",
            "primary_domain_name": f"Domain {i % 3}",
            "countries": "CN" if i % 5 == 0 else "US",
            "is_oa": i % 2 == 0,
            "pdf_url": f"https://example.com/{i}.pdf" if i % 3 == 0 else None,
            "landing_url": f"https://doi.org/10.1234/test.{i}",
        })
    return works
