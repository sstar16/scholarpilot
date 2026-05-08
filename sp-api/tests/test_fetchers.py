"""Fetcher registry smoke test。"""


def test_all_fetchers_registered():
    from app.services.fetchers.international import ALL_FETCHERS

    assert len(ALL_FETCHERS) >= 12, f"only {len(ALL_FETCHERS)} fetchers"

    expected = {
        "pubmed", "openalex", "openalex_zh", "europe_pmc", "arxiv",
        "biorxiv", "medrxiv", "semantic_scholar", "uspto", "lens_patent",
        "clinical_trials", "crossref", "dblp", "epo_ops", "patenthub",
        # 2026-05-08 LDR-inspired 扩展
        "wikipedia", "tavily", "zenodo", "duckduckgo", "github", "stackexchange",
    }
    missing = expected - set(ALL_FETCHERS.keys())
    assert not missing, f"fetchers missing: {missing}"


def test_fetcher_registry_metadata():
    from app.services.fetchers.base import FetcherRegistry

    info = FetcherRegistry.get_all_info()
    assert isinstance(info, list)
    assert len(info) >= 14
    for entry in info:
        assert "id" in entry
        assert "name" in entry
        assert "doc_type" in entry


def test_paid_pdf_marker():
    """PatentHub 必须 PAID_PDF=True。"""
    from app.services.fetchers.international import ALL_FETCHERS

    patenthub = ALL_FETCHERS.get("patenthub")
    assert patenthub is not None
    assert getattr(patenthub, "PAID_PDF", False) is True

    # OpenAlex 不付费
    openalex = ALL_FETCHERS["openalex"]
    assert getattr(openalex, "PAID_PDF", False) is False
