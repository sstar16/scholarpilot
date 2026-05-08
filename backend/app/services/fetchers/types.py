"""Source-id Literal + 注册表完备性检查。

把"新增源 4 步"从 CLAUDE.md 文档约束变成类型/运行期约束：
  - mypy 拒绝 ``ALL_FETCHERS["openalexx"]`` 这种拼错的 key
  - 模块加载时强制 ``set(ALL_FETCHERS.keys()) | {local_kb}`` 必须等于
    ``ALL_SOURCE_IDS``，漏注册一个直接 RuntimeError，不到运行期检索时再炸

新增/重命名/删除源时，更新 ``SourceId`` Literal —— 编译期 + import 期
都会立刻把所有不一致点报出来。
"""
from __future__ import annotations

from typing import Literal, get_args

# Canonical list of all known source IDs (must match FetcherRegistry.SOURCES
# and ALL_FETCHERS in international.py).
SourceId = Literal[
    "pubmed",
    "openalex",
    "semantic_scholar",
    "europe_pmc",
    "arxiv",
    "biorxiv",
    "medrxiv",
    "dblp",
    "openalex_zh",
    "uspto",
    "lens_patent",
    "epo_ops",
    "patenthub",
    "bigquery_patents",
    "clinical_trials",
    "crossref",
    "local_kb",
]


ALL_SOURCE_IDS: frozenset[str] = frozenset(get_args(SourceId))


# Sources that are conditionally registered at import time (e.g. local_kb only
# loads when the data dir exists). They count toward exhaustiveness but their
# absence in the runtime dict is not an error.
CONDITIONAL_SOURCE_IDS: frozenset[str] = frozenset({"local_kb"})


def assert_registry_exhaustive(registered: dict) -> None:
    """Raise if the runtime fetcher registry is missing required ids or has
    keys that are not declared in :data:`SourceId`."""
    actual = set(registered.keys())
    expected = set(ALL_SOURCE_IDS)
    missing = expected - actual - CONDITIONAL_SOURCE_IDS
    if missing:
        raise RuntimeError(
            f"Fetcher registry missing required source ids: {sorted(missing)}. "
            f"Either register them in ALL_FETCHERS or remove them from SourceId."
        )
    unknown = actual - expected
    if unknown:
        raise RuntimeError(
            f"Fetcher registry has unknown source ids: {sorted(unknown)}. "
            f"Either add them to SourceId or remove the registration."
        )


def is_valid_source_id(value: str) -> bool:
    """Runtime check (e.g. for env-var parsing)."""
    return value in ALL_SOURCE_IDS
