# Data Source Access Policies

## Enabled Sources (as of 2026-04-01)
- OpenAlex, EuropePMC, Crossref, DBLP, arXiv, bioRxiv, medRxiv, OpenAlex_zh
- EPO OPS, SooPat, Lens.org (with valid tokens)

## Disabled Sources (via DISABLED_SOURCES env var)
- PubMed (GFW blocked)
- ClinicalTrials.gov (GFW blocked)
- Semantic Scholar (429 rate limits)
- USPTO PatentsView (API discontinued)

## Adding New Sources
1. Create fetcher class inheriting `AbstractFetcher` in `backend/app/services/fetchers/`
2. Add metadata to `FetcherRegistry.SOURCES` in `base.py`
3. Add instance to `ALL_FETCHERS` dict in `international.py`
4. Tool Registry auto-registers at startup (no extra step needed)
