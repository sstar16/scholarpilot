"""
Per-Source Query Adapters
每个数据源有独立的查询词优化 adapter，基于 API 真实能力做差异化。
支持 LLM 批量优化 + heuristic fallback。

API 研究结果：
- OpenAlex: 3-5 词，支持 "phrase" AND/OR/NOT，Elasticsearch
- arXiv: 2-3 个 AND 词（多了=0结果），all: 前缀，ANDNOT
- Crossref: 3-5 自然语言，不支持布尔/短语，用 query.bibliographic=
- Europe PMC: 3-6 词，TITLE:"kw" 字段检索，默认 MeSH 同义词扩展
- EPO OPS: 2-4 + IPC 分类号，ta="kw"(标题+摘要)，CQL
- DBLP: 2 个极精简词，前缀匹配，只有 CS
- bioRxiv/medRxiv: API 无关键词搜索，只按日期拉全量
- OpenAlex zh: language:zh 有效但关键词数 ≤3 个，否则 0 结果
"""
import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple

from app.services.fetchers.base import FetcherRegistry

logger = logging.getLogger(__name__)


# ─── 数据结构 ───────────────────────────────────────────────

@dataclass
class SourceKeywordPlan:
    source_id: str
    display_name: str
    query: str
    query_format: str       # "plain" | "cql" | "boolean" | "bibliographic" | "chinese" | "field"
    language: str            # "en" | "zh" | "multilingual"
    enabled: bool
    generation_method: str   # "llm" | "heuristic" | "passthrough"
    notes: str
    category: str = "literature"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PerSourceKeywordResult:
    round_id: str
    base_query: str
    original_chinese_query: Optional[str]
    source_plans: List[SourceKeywordPlan]
    generation_time_ms: int
    synonyms: Optional[Dict[str, List[str]]] = None  # 动态同义词表

    def to_dict(self) -> dict:
        return {
            "round_id": self.round_id,
            "base_query": self.base_query,
            "original_chinese_query": self.original_chinese_query,
            "source_plans": [p.to_dict() for p in self.source_plans],
            "generation_time_ms": self.generation_time_ms,
            "synonyms": self.synonyms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PerSourceKeywordResult":
        return cls(
            round_id=d["round_id"],
            base_query=d["base_query"],
            original_chinese_query=d.get("original_chinese_query"),
            source_plans=[SourceKeywordPlan(**p) for p in d["source_plans"]],
            generation_time_ms=d.get("generation_time_ms", 0),
            synonyms=d.get("synonyms"),
        )


# ─── 工具函数 ──────────────────────────────────────────────

# 学术搜索中无意义的通用词（不应作为关键词）
_ADAPTER_STOPWORDS = {
    "second", "first", "third", "based", "using", "study", "analysis",
    "method", "approach", "system", "design", "development", "research",
    "novel", "new", "improved", "advanced", "high", "low", "large", "small",
    "100", "per", "drops", "drop",
}


def _top_words(query: str, n: int, min_len: int = 3) -> List[str]:
    """取查询中最长（最具体）的 N 个词，过滤停用词"""
    words = [w for w in query.split()
             if len(w) >= min_len and w.lower() not in _ADAPTER_STOPWORDS]
    words.sort(key=len, reverse=True)
    return words[:n]


def _limit_chinese_terms(query: str, n: int) -> str:
    """限制中文查询词数量（OpenAlex 多了返回 0）"""
    cn_pat = re.compile(r'[\u4e00-\u9fff]+')
    terms = cn_pat.findall(query)
    if len(terms) <= n:
        return query
    return " ".join(terms[:n])


# ─── Adapter 基类 ──────────────────────────────────────────

class BaseSourceQueryAdapter(ABC):
    source_id: str
    query_format: str = "plain"

    @abstractmethod
    def adapt(
        self,
        base_query: str,
        chinese_query: Optional[str],
        project_description: str,
        llm_hints: Optional[Dict[str, str]] = None,
    ) -> str:
        pass

    def get_notes(self) -> str:
        return ""


# ─── 具体 Adapter ─────────────────────────────────────────

class OpenAlexAdapter(BaseSourceQueryAdapter):
    """OpenAlex: 3-5 词，支持 "phrase" 和 AND/OR。Elasticsearch 后端。"""

    def __init__(self):
        self.source_id = "openalex"
        self.query_format = "boolean"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        # 取最具体的 5 个词，用空格连接（OpenAlex 默认 AND）
        words = _top_words(base_query, 5)
        return " ".join(words) if words else base_query

    def get_notes(self):
        return "全领域学术库，3-5 关键词，支持 \"短语\" AND/OR"


class OpenAlexZhAdapter(BaseSourceQueryAdapter):
    """
    OpenAlex 中文: 双策略查询 (zh_query|||en_query)
    策略A: 2-3 中文词 + language:zh
    策略B: 英文词 + country_code:cn
    用 ||| 分隔传给 fetcher，fetcher 解析后分别执行。
    """

    def __init__(self):
        self.source_id = "openalex_zh"
        self.query_format = "dual"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            hint = llm_hints[self.source_id]
            # LLM 可能已返回 dual 格式
            if "|||" in hint:
                return hint
            # LLM 只返回中文部分，补上英文
            return f"{hint}|||{' '.join(_top_words(base_query, 4))}"
        zh_part = _limit_chinese_terms(chinese_query, 3) if chinese_query else ""
        en_part = " ".join(_top_words(base_query, 4))
        return f"{zh_part}|||{en_part}"

    def get_notes(self):
        return "双策略: 中文词(language:zh) + 英文词(country:cn)"


class ArXivAdapter(BaseSourceQueryAdapter):
    """arXiv: 2-3 个 AND 词（过多=0结果），all: 前缀"""

    def __init__(self):
        self.source_id = "arxiv"
        self.query_format = "boolean"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        # 只取 2-3 个最具体的词，避免过多导致 0 结果
        words = _top_words(base_query, 3)
        return " ".join(words) if words else base_query

    def get_notes(self):
        return "预印本，限 2-3 关键词（过多=0 结果）"


class CrossrefAdapter(BaseSourceQueryAdapter):
    """Crossref: 不支持布尔/短语，3-5 自然语言词，建议用 query.bibliographic="""

    def __init__(self):
        self.source_id = "crossref"
        self.query_format = "bibliographic"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        # 取 4 个最具体的词，自然语言风格
        words = _top_words(base_query, 4)
        return " ".join(words) if words else base_query

    def get_notes(self):
        return "文献元数据，不支持布尔，3-5 自然语言词"


class EuropePMCAdapter(BaseSourceQueryAdapter):
    """Europe PMC: 支持 TITLE:"kw" 字段检索，默认 MeSH 同义词扩展"""

    def __init__(self):
        self.source_id = "europe_pmc"
        self.query_format = "field"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        # 用空格连接（Europe PMC 默认 AND），取 4-5 词
        words = _top_words(base_query, 5)
        return " ".join(words) if words else base_query

    def get_notes(self):
        return "生物医学，支持 MeSH 同义词扩展，3-6 关键词"


class EPOAdapter(BaseSourceQueryAdapter):
    """EPO OPS: 传入 2-3 个简短关键词（fetcher 自动转 CQL ti/ab 格式）"""

    def __init__(self):
        self.source_id = "epo_ops"
        self.query_format = "plain"  # fetcher 自己构建 CQL

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        # EPO fetcher 自己会把 plain words 转成 CQL，这里只需提供 2-3 个精准词
        # 避免连字符（EPO CQL 对连字符敏感），用空格替换
        words = _top_words(base_query, 3, min_len=3)
        cleaned = [w.replace("-", " ") for w in words]
        return " ".join(cleaned) if cleaned else base_query

    def get_notes(self):
        return "欧洲专利，2-3 关键词（自动转 CQL ti/ab）"


class DBLPAdapter(BaseSourceQueryAdapter):
    """DBLP: 只有 CS，前缀匹配，2 个极精简词"""

    def __init__(self):
        self.source_id = "dblp"
        self.query_format = "plain"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        # 只取 2 个最长（最具体）的词
        words = _top_words(base_query, 2, min_len=4)
        return " ".join(words) if words else base_query

    def get_notes(self):
        return "CS 会议/期刊，仅 2 个核心词，前缀匹配"


class BioRxivAdapter(BaseSourceQueryAdapter):
    """bioRxiv/medRxiv: API 不支持关键词搜索，只能按日期拉全量后本地过滤"""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.query_format = "plain"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        # 关键词仅用于本地过滤，取 3-4 词
        return " ".join(_top_words(base_query, 4))

    def get_notes(self):
        return "预印本，API 仅日期范围，关键词用于本地过滤"


class ChineseSourceAdapter(BaseSourceQueryAdapter):
    """中文数据源（SooPat等）：使用 2-4 个精准中文关键词"""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.query_format = "chinese"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        if chinese_query:
            return _limit_chinese_terms(chinese_query, 4)
        # fallback: 从描述提取中文关键词
        cn_pat = re.compile(r'[\u4e00-\u9fff]{2,}')
        words = cn_pat.findall(project_description[:200])
        stop = {"的", "了", "在", "是", "和", "与", "研究", "开发", "项目", "我们", "进行", "通过", "实现"}
        meaningful = [w for w in words if w not in stop]
        return " ".join(meaningful[:4]) if meaningful else base_query

    def get_notes(self):
        return "中文检索，2-4 个精准中文关键词"


class LensAdapter(BaseSourceQueryAdapter):
    """Lens.org: 全球专利，plain text，3-5 词"""

    def __init__(self):
        self.source_id = "lens_patent"
        self.query_format = "plain"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        return " ".join(_top_words(base_query, 5))

    def get_notes(self):
        return "全球专利 (90+ 国家)，3-5 关键词"


class DefaultAdapter(BaseSourceQueryAdapter):
    """默认 passthrough"""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.query_format = "plain"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        return base_query

    def get_notes(self):
        return ""


# ─── Adapter 注册表 ────────────────────────────────────────

_CHINESE_SOURCE_IDS = {
    k for k, v in FetcherRegistry.SOURCES.items()
    if v.get("language") == "zh"
} | {"openalex_zh"}

_ADAPTER_REGISTRY: Dict[str, BaseSourceQueryAdapter] = {}


def _build_adapter_registry() -> Dict[str, BaseSourceQueryAdapter]:
    registry = {}
    # 基于 API 研究的专用 adapters
    registry["openalex"] = OpenAlexAdapter()
    registry["openalex_zh"] = OpenAlexZhAdapter()
    registry["arxiv"] = ArXivAdapter()
    registry["crossref"] = CrossrefAdapter()
    registry["europe_pmc"] = EuropePMCAdapter()
    registry["epo_ops"] = EPOAdapter()
    registry["dblp"] = DBLPAdapter()
    registry["lens_patent"] = LensAdapter()
    registry["biorxiv"] = BioRxivAdapter("biorxiv")
    registry["medrxiv"] = BioRxivAdapter("medrxiv")

    # 中文数据源
    for sid in _CHINESE_SOURCE_IDS:
        if sid not in registry:
            registry[sid] = ChineseSourceAdapter(sid)

    # 其余
    for sid in FetcherRegistry.SOURCES:
        if sid not in registry:
            registry[sid] = DefaultAdapter(sid)

    return registry


def get_adapter(source_id: str) -> BaseSourceQueryAdapter:
    global _ADAPTER_REGISTRY
    if not _ADAPTER_REGISTRY:
        _ADAPTER_REGISTRY = _build_adapter_registry()
    return _ADAPTER_REGISTRY.get(source_id, DefaultAdapter(source_id))


# ─── LLM 批量优化（含动态同义词生成）─────────────────────────

# 每个源的 API 语法规则，传给 LLM 让它生成符合格式的查询
_SOURCE_RULES = {
    "openalex": "3-5 English keywords, supports \"phrase\" and AND/OR. Elasticsearch backend.",
    "openalex_zh": "Dual format: 'chinese_terms|||english_terms'. Chinese: 2-3 words. English: 3-4 words. Example: '爆珠 自动化|||seamless capsule automated production'.",
    "arxiv": "2-3 English keywords only (more = 0 results). No Boolean needed.",
    "crossref": "3-5 natural language words. No Boolean or phrase support. Title/author focused.",
    "europe_pmc": "3-6 English keywords. Can use TITLE:\"keyword\". MeSH synonyms auto-expand.",
    "epo_ops": "2-3 plain English keywords (NO CQL syntax, NO hyphens). The system auto-converts to CQL.",
    "dblp": "2 very specific CS terms only. Prefix matching. CS conferences/journals only.",
    "biorxiv": "3-4 English keywords for local filtering (API has no search). Biology focused.",
    "medrxiv": "3-4 English keywords for local filtering (API has no search). Medicine focused.",
    "lens_patent": "3-5 English patent keywords. Plain text search.",
    "soopat": "2-4 precise Chinese patent keywords. Space-separated.",
}


async def _llm_optimize_single(
    source_id: str,
    base_query: str,
    chinese_query: Optional[str],
    project_description: str,
    llm_manager,
) -> Optional[str]:
    """单个数据源的 LLM 关键词优化（轻量 prompt，快速返回）"""
    rule = _SOURCE_RULES.get(source_id, "Plain keywords")

    prompt = (
        f"Optimize search keywords for the '{source_id}' database.\n\n"
        f"Research topic: {project_description[:300]}\n"
        f"Base English keywords: {base_query}\n"
        f"Base Chinese keywords: {chinese_query or '(none)'}\n\n"
        f"Database rule: {rule}\n\n"
        "Return ONLY the optimized query string, nothing else. "
        "Use domain-specific terms, not generic words."
    )

    try:
        result = await asyncio.wait_for(
            llm_manager.generate(prompt, temperature=0.1),
            timeout=12.0,
        )
        if result:
            # 清理：去除引号和多余空白
            cleaned = result.strip().strip('"').strip("'").strip()
            if cleaned and len(cleaned) > 2:
                return cleaned
    except asyncio.TimeoutError:
        logger.warning("[SourceAdapters] LLM 优化超时: %s", source_id)
    except Exception as e:
        logger.warning("[SourceAdapters] LLM 优化失败 %s: %s", source_id, e)

    return None


async def _llm_generate_synonyms(
    base_query: str,
    chinese_query: Optional[str],
    project_description: str,
    llm_manager,
) -> Optional[Dict[str, List[str]]]:
    """单独一次 LLM 调用生成同义词表（与关键词优化并行）"""
    prompt = (
        "Generate domain-specific synonym mappings for academic search scoring.\n\n"
        f"Research topic: {project_description[:300]}\n"
        f"Key terms: {base_query}\n"
        f"Chinese terms: {chinese_query or '(none)'}\n\n"
        "Return JSON: {\"english_term\": [\"synonym1\", \"synonym2\", ...]} "
        "with 5-10 synonym groups. Include Chinese equivalents. "
        "Return ONLY JSON."
    )

    try:
        result = await asyncio.wait_for(
            llm_manager.generate(prompt, temperature=0.1),
            timeout=12.0,
        )
        if result:
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    return {
                        str(k): [str(s) for s in v] if isinstance(v, list) else []
                        for k, v in parsed.items()
                    }
    except asyncio.TimeoutError:
        logger.warning("[SourceAdapters] 同义词生成超时")
    except Exception as e:
        logger.warning("[SourceAdapters] 同义词生成失败: %s", e)

    return None


async def _llm_parallel_optimize(
    base_query: str,
    chinese_query: Optional[str],
    project_description: str,
    source_ids: List[str],
    llm_manager,
) -> Tuple[Dict[str, str], Optional[Dict[str, List[str]]]]:
    """
    并行为每个源独立调用 LLM 优化关键词 + 并行生成同义词。
    单源失败不影响其他源。
    """
    if not llm_manager:
        return {}, None

    # 并行：每源一个轻量 LLM 调用 + 一个同义词调用
    source_tasks = {
        sid: _llm_optimize_single(sid, base_query, chinese_query, project_description, llm_manager)
        for sid in source_ids
    }
    synonym_task = _llm_generate_synonyms(base_query, chinese_query, project_description, llm_manager)

    # 全部并行执行
    all_tasks = list(source_tasks.values()) + [synonym_task]
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    # 拆分结果
    source_results = results[:len(source_ids)]
    synonym_result = results[-1]

    hints: Dict[str, str] = {}
    for sid, result in zip(source_ids, source_results):
        if isinstance(result, str) and result:
            hints[sid] = result

    synonyms = synonym_result if isinstance(synonym_result, dict) else None

    succeeded = len(hints)
    logger.info(
        "[SourceAdapters] 并行 LLM 优化: %d/%d 源成功, 同义词: %s",
        succeeded, len(source_ids),
        f"{len(synonyms)} 组" if synonyms else "失败",
    )

    return hints, synonyms


# ─── 主入口 ────────────────────────────────────────────────

async def generate_all_keywords(
    round_id: str,
    base_query: str,
    original_chinese_query: Optional[str],
    project_description: str,
    sources: List[str],
    llm_manager=None,
    disabled_sources: Optional[set] = None,
) -> PerSourceKeywordResult:
    """
    为所有活跃数据源生成优化查询词。
    先尝试 LLM 批量优化，再用 heuristic adapter 生成/补全。
    """
    t0 = time.time()
    disabled = disabled_sources or set()

    # Step 1: 并行 LLM 优化（每源独立调用，互不阻塞）
    llm_hints, synonyms = await _llm_parallel_optimize(
        base_query, original_chinese_query, project_description,
        [s for s in sources if s not in disabled],
        llm_manager,
    )

    # Step 2: 对每个源用 adapter 生成最终查询词
    plans: List[SourceKeywordPlan] = []
    for source_id in sources:
        meta = FetcherRegistry.SOURCES.get(source_id, {})
        adapter = get_adapter(source_id)
        is_disabled = source_id in disabled

        query = adapter.adapt(
            base_query=base_query,
            chinese_query=original_chinese_query,
            project_description=project_description,
            llm_hints=llm_hints,
        )

        if source_id in llm_hints:
            method = "llm"
        elif isinstance(adapter, DefaultAdapter):
            method = "passthrough"
        else:
            method = "heuristic"

        plans.append(SourceKeywordPlan(
            source_id=source_id,
            display_name=meta.get("name", source_id),
            query=query,
            query_format=adapter.query_format,
            language=meta.get("language", "en"),
            enabled=not is_disabled,
            generation_method=method,
            notes=adapter.get_notes(),
            category=meta.get("category", "literature"),
        ))

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        "[SourceAdapters] 生成 %d 个源的查询词，耗时 %dms (LLM: %d 个优化, %d 同义词组)",
        len(plans), elapsed_ms, len(llm_hints),
        len(synonyms) if synonyms else 0,
    )

    return PerSourceKeywordResult(
        round_id=round_id,
        base_query=base_query,
        original_chinese_query=original_chinese_query,
        source_plans=plans,
        generation_time_ms=elapsed_ms,
        synonyms=synonyms,
    )
