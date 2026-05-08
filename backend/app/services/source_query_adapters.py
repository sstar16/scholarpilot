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
    query: str                  # primary (complex) — 首次尝试
    query_format: str       # "plain" | "cql" | "boolean" | "bibliographic" | "chinese" | "field"
    language: str            # "en" | "zh" | "multilingual"
    enabled: bool
    generation_method: str   # "llm" | "heuristic" | "passthrough"
    notes: str
    category: str = "literature"
    # 三层降级：complex(=query) → medium → simple。
    # 空字符串 / 与上一层重复 → 该层跳过（execute_search 会去重）。
    query_medium: str = ""
    query_simple: str = ""

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

def _top_words(query: str, n: int, min_len: int = 3) -> List[str]:
    """
    按原位置保留前 N 个非停用词 token。
    保护词序和相邻关系，避免打散 `lithium iron phosphate` 这类复合名词。
    停用词来自 common.stopwords.EN_STOPWORDS（统一维护）。
    """
    from app.services.common.stopwords import EN_STOPWORDS
    out: List[str] = []
    for w in query.split():
        if len(w) >= min_len and w.lower() not in EN_STOPWORDS:
            out.append(w)
        if len(out) >= n:
            break
    return out


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
    """中文数据源（PatentHub / 百度学术等）：使用 2-4 个精准中文关键词"""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.query_format = "chinese"

    def adapt(self, base_query, chinese_query, project_description, llm_hints=None):
        if llm_hints and self.source_id in llm_hints:
            return llm_hints[self.source_id]
        if chinese_query:
            return _limit_chinese_terms(chinese_query, 4)
        # fallback: 用 jieba 分词从描述抽中文关键词（修既有"正则连续 CJK 不分词"bug）
        from app.services.common.stopwords import ZH_STOPWORDS
        import jieba
        tokens = [
            w for w in jieba.cut(project_description[:500])
            if len(w) >= 2 and w not in ZH_STOPWORDS and re.search(r'[\u4e00-\u9fff]', w)
        ]
        return " ".join(tokens[:4]) if tokens else base_query

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

# 每源的 API 规则已搬到 backend/app/prompts/sources/<source_id>.md
# 改 md 即可修改 LLM 看到的规则，无需重启 worker（mtime 热重载）
_DEFAULT_SOURCE_RULE = "Plain English keywords, 3-5 terms."


async def _llm_optimize_single(
    source_id: str,
    base_query: str,
    chinese_query: Optional[str],
    project_description: str,
    llm_manager,
) -> Optional[str]:
    """单个数据源的 LLM 关键词优化（规则从 sources/<source_id>.md 读取）"""
    from app.services.prompt_loader import load_prompt

    try:
        rule = load_prompt(f"sources/{source_id}").body
    except FileNotFoundError:
        rule = _DEFAULT_SOURCE_RULE

    prompt = (
        f"Optimize search keywords for the '{source_id}' database.\n\n"
        f"Research topic: {project_description[:300]}\n"
        f"Base English keywords: {base_query}\n"
        f"Base Chinese keywords: {chinese_query or '(none)'}\n\n"
        f"Database rules:\n{rule}\n\n"
        "Return ONLY the optimized query string, nothing else. "
        "Use domain-specific terms, not generic words."
    )

    try:
        result = await asyncio.wait_for(
            llm_manager.generate(prompt, temperature=0.1),
            timeout=30.0,
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
            llm_manager.generate(
                prompt, temperature=0.1,
                response_format={"type": "json_object"},
            ),
            timeout=30.0,
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


async def _llm_batch_optimize(
    base_query: str,
    chinese_query: Optional[str],
    project_description: str,
    source_ids: List[str],
    llm_manager,
) -> Dict[str, Dict[str, str]]:
    """
    一次 LLM 调用批量为所有源生成 3 层降级 query（complex/medium/simple）。
    prompt + 规则从 prompts/strategies/per_source_batch.md + sources/<sid>.md 拼接。
    失败时返回空 dict（上层会降级到 _llm_parallel_single）。
    返回格式：{source_id: {"complex": "...", "medium": "...", "simple": "..."}}
    """
    if not llm_manager or not source_ids:
        return {}

    from app.services.prompt_loader import load_prompt

    # 拼接每个源的规则（来自 sources/<sid>.md 的 body）
    rules_parts = []
    for sid in source_ids:
        try:
            pf = load_prompt(f"sources/{sid}")
            rules_parts.append(f"### {sid}\n\n{pf.body}")
        except FileNotFoundError:
            rules_parts.append(f"### {sid}\n\n(no specific rules, use 3-5 plain English keywords)")
    sources_rules = "\n\n---\n\n".join(rules_parts)

    try:
        batch_tpl = load_prompt("strategies/per_source_batch")
    except FileNotFoundError:
        logger.warning("[SourceAdapters] strategies/per_source_batch.md 缺失")
        return {}

    prompt = batch_tpl.render(
        research_topic=project_description[:500],
        base_english=base_query,
        base_chinese=chinese_query or "(none)",
        sources_rules=sources_rules,
    )

    try:
        result = await asyncio.wait_for(
            llm_manager.generate(
                prompt, temperature=0.1,
                response_format={"type": "json_object"},
                max_tokens=8000,  # 14 源 × 3 层布尔桶 JSON 较大；推理模型 reasoning 占大头，显式申请上限防截断
            ),
            timeout=90.0,  # 批量比单源大，允许更长
        )
    except asyncio.TimeoutError:
        logger.warning("[SourceAdapters] 批量 LLM 优化超时")
        return {}
    except Exception as e:
        logger.warning("[SourceAdapters] 批量 LLM 优化失败: %s", e)
        return {}

    if not result:
        return {}

    # 清理 markdown 代码块包裹
    cleaned = result.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned)

    # 提取 JSON 对象
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        logger.warning("[SourceAdapters] 批量结果无 JSON: %s", result[:200])
        return {}

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError as e:
        logger.warning("[SourceAdapters] 批量 JSON 解析失败: %s", e)
        return {}

    if not isinstance(parsed, dict):
        return {}

    def _clean_one(sid: str, q) -> str:
        if not isinstance(q, str):
            return ""
        s = q.strip().strip("'").strip()
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"' and s.count('"') == 2:
            s = s[1:-1].strip()
        s = _sanitize_source_query(sid, s)
        return s if s and len(s) > 2 else ""

    # 支持两种格式：
    #   新: {sid: {complex, medium, simple}}
    #   旧: {sid: "query"}  → 视为只有 complex 层
    out: Dict[str, Dict[str, str]] = {}
    for sid, v in parsed.items():
        if isinstance(v, dict):
            complex_q = _clean_one(sid, v.get("complex", ""))
            medium_q = _clean_one(sid, v.get("medium", ""))
            simple_q = _clean_one(sid, v.get("simple", ""))
            if not complex_q and not medium_q and not simple_q:
                continue
            out[sid] = {"complex": complex_q, "medium": medium_q, "simple": simple_q}
        elif isinstance(v, str):
            c = _clean_one(sid, v)
            if c:
                out[sid] = {"complex": c, "medium": "", "simple": ""}
    return out


def _sanitize_source_query(source_id: str, query: str) -> str:
    """
    对单个源的 LLM 输出做 sanity 后处理：
    1. 引号数量奇数 → 删掉所有双引号（退化为无短语匹配，避免 API 500）
    2. 超过 md.max_terms → 按词（或短语 "phrase"）截断
    3. 对 dual 格式源（openalex_zh）中 `|||` 的两边分别处理
    """
    if not query:
        return query

    # dual 格式：对两边分别 sanitize
    if "|||" in query:
        parts = query.split("|||", 1)
        left = _sanitize_source_query(source_id + "_zh_part", parts[0])
        right = _sanitize_source_query(source_id + "_en_part", parts[1])
        return f"{left}|||{right}"

    # 1. 奇数引号 → 全删
    if query.count('"') % 2 == 1:
        logger.warning(
            "[SourceAdapters] %s query 引号不对称 (%d 个)，已全部移除: %r",
            source_id, query.count('"'), query[:80],
        )
        query = query.replace('"', '')

    # 读 md frontmatter 里的限制参数
    try:
        from app.services.prompt_loader import load_prompt
        pf = load_prompt(f"sources/{source_id}")
        max_terms = pf.get("max_terms")
        max_phrases = pf.get("max_phrases")
    except FileNotFoundError:
        max_terms = None
        max_phrases = None

    # 2. 限制 phrase 数量（过多严格短语会导致 0 命中）
    if isinstance(max_phrases, int) and max_phrases >= 0:
        phrases = re.findall(r'"[^"]+"', query)
        if len(phrases) > max_phrases:
            logger.info(
                "[SourceAdapters] %s phrase 数超限 (%d > %d)，多余的去掉引号: %r",
                source_id, len(phrases), max_phrases, query[:80],
            )
            # 保留前 max_phrases 个短语，剩下的脱掉引号
            for i, phrase in enumerate(phrases):
                if i >= max_phrases:
                    query = query.replace(phrase, phrase.strip('"'), 1)

    # 布尔桶格式（如 (A OR B) AND (C OR D)）跳过词数截断：
    # 原逻辑"保留所有 AND/OR + 只保留前 N 个 payload"会导致被截断词前后的 OR 残留，
    # 产生 "检测 OR 缺陷 OR 剔除 OR OR OR OR" 这种碎片。
    has_boolean = bool(re.search(r'\b(AND|OR|ANDNOT)\b', query))

    if isinstance(max_terms, int) and max_terms > 0 and not has_boolean:
        # 按短语（"xxx"）或单词切分，保留前 max_terms 个
        tokens = re.findall(r'"[^"]+"|\S+', query)
        payload = tokens  # 无布尔 → 每个 token 都是 payload
        if len(payload) > max_terms:
            logger.info(
                "[SourceAdapters] %s 词数超限 (%d > %d)，截断: %r → 前 %d",
                source_id, len(payload), max_terms, query[:80], max_terms,
            )
            query = " ".join(payload[:max_terms]).strip()

    return query.strip()


async def _llm_parallel_single(
    base_query: str,
    chinese_query: Optional[str],
    project_description: str,
    source_ids: List[str],
    llm_manager,
) -> Dict[str, Dict[str, str]]:
    """
    降级路径：每源一次 LLM 调用的并行优化（batch 失败时使用）。
    单源失败不影响其他源。返回 {sid: {complex, medium, simple}}，单源 LLM 只产 complex，
    medium/simple 留空（后续在 generate_all_keywords 里由规则推导补齐）。
    """
    if not llm_manager or not source_ids:
        return {}

    source_tasks = {
        sid: _llm_optimize_single(sid, base_query, chinese_query, project_description, llm_manager)
        for sid in source_ids
    }
    results = await asyncio.gather(*source_tasks.values(), return_exceptions=True)

    hints: Dict[str, Dict[str, str]] = {}
    for sid, result in zip(source_ids, results):
        if isinstance(result, str) and result:
            q = _sanitize_source_query(sid, result)
            if q:
                hints[sid] = {"complex": q, "medium": "", "simple": ""}
    return hints


async def _llm_parallel_optimize(
    base_query: str,
    chinese_query: Optional[str],
    project_description: str,
    source_ids: List[str],
    llm_manager,
) -> Tuple[Dict[str, Dict[str, str]], Optional[Dict[str, List[str]]]]:
    """
    主路径：1 次 batch query 优化 + 1 次 synonyms 生成，共 2 次 LLM 调用。
    batch 失败 → 降级到 _llm_parallel_single（N 次单源调用）。
    返回 ({sid: {complex, medium, simple}}, synonyms)。
    """
    if not llm_manager:
        return {}, None

    # 两个独立任务并行：batch 优化 + synonyms
    batch_task = _llm_batch_optimize(
        base_query, chinese_query, project_description, source_ids, llm_manager
    )
    synonym_task = _llm_generate_synonyms(
        base_query, chinese_query, project_description, llm_manager
    )
    batch_result, synonym_result = await asyncio.gather(
        batch_task, synonym_task, return_exceptions=True
    )

    hints: Dict[str, Dict[str, str]] = batch_result if isinstance(batch_result, dict) else {}
    synonyms = synonym_result if isinstance(synonym_result, dict) else None

    # 批量失败（或命中率极低）→ 降级到并行单源调用
    if len(hints) < max(1, len(source_ids) // 2):
        logger.warning(
            "[SourceAdapters] 批量命中率低 (%d/%d)，降级到并行单源调用",
            len(hints), len(source_ids),
        )
        fallback_hints = await _llm_parallel_single(
            base_query, chinese_query, project_description, source_ids, llm_manager
        )
        # 合并：batch 成功的优先保留，其余用单源补齐
        for sid, tiers in fallback_hints.items():
            hints.setdefault(sid, tiers)

    logger.info(
        "[SourceAdapters] LLM 优化: %d/%d 源成功, 同义词: %s",
        len(hints), len(source_ids),
        f"{len(synonyms)} 组" if synonyms else "失败",
    )

    return hints, synonyms


def _derive_fallback_tiers(source_id: str, complex_q: str) -> Tuple[str, str]:
    """
    当 LLM 只给了 complex（或完全没给，退化到 adapter）时，根据规则推导 medium / simple：
      - simple = 保留前 2-3 个核心词，去掉所有引号和布尔操作符
      - medium = 保留前 ~60% 词，脱去最外围短语（如果有 2 个以上短语）
    对中文查询走中文分词路径；dual 格式（|||）两边分别处理。
    """
    if not complex_q:
        return "", ""

    if "|||" in complex_q:
        left_c, right_c = complex_q.split("|||", 1)
        left_m, left_s = _derive_fallback_tiers(source_id + "_zh_part", left_c)
        right_m, right_s = _derive_fallback_tiers(source_id + "_en_part", right_c)
        return f"{left_m}|||{right_m}", f"{left_s}|||{right_s}"

    # 是否中文查询
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', complex_q))

    # 读 md 的 max_terms 作为天花板
    try:
        from app.services.prompt_loader import load_prompt
        pf = load_prompt(f"sources/{source_id}")
        max_terms = pf.get("max_terms") or 5
    except Exception:
        max_terms = 5
    max_terms = int(max_terms) if isinstance(max_terms, (int, float, str)) and str(max_terms).isdigit() else 5

    simple_n = max(2, min(3, max_terms))
    medium_n = max(simple_n, max(2, int(max_terms * 0.7)))

    if has_chinese:
        # 中文：按空格或非 CJK 分隔取词，去停用词
        from app.services.common.stopwords import ZH_STOPWORDS
        terms = [t for t in re.split(r'[\s,，、;]+', complex_q) if t]
        zh_terms = [t for t in terms if re.search(r'[\u4e00-\u9fff]', t) and t not in ZH_STOPWORDS]
        medium = " ".join(zh_terms[:medium_n]) if zh_terms else complex_q
        simple = " ".join(zh_terms[:simple_n]) if zh_terms else complex_q
        return medium, simple

    # 英文：剥引号、剥布尔操作符、取前 N 个非停用词
    stripped = complex_q.replace('"', ' ')
    stripped = re.sub(r'\b(AND|OR|NOT|ANDNOT)\b', ' ', stripped, flags=re.IGNORECASE)
    words = _top_words(stripped, medium_n, min_len=3)
    if not words:
        return "", ""
    medium = " ".join(words[:medium_n])
    simple = " ".join(words[:simple_n])
    return medium, simple


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

    # adapter.adapt() 还是用 {sid: str} 形式，抽出 complex 层给它
    complex_hints: Dict[str, str] = {
        sid: tiers.get("complex", "")
        for sid, tiers in llm_hints.items()
        if tiers.get("complex")
    }

    # Step 2: 对每个源用 adapter 生成最终查询词
    plans: List[SourceKeywordPlan] = []
    # LLM 完全失败时所有源都走 adapter fallback（原行为）
    # LLM 部分成功但漏掉某源时，视为"LLM 判定不适合"，默认关闭那个源
    llm_hints_empty = not llm_hints

    for source_id in sources:
        meta = FetcherRegistry.SOURCES.get(source_id, {})
        adapter = get_adapter(source_id)
        is_disabled = source_id in disabled

        # complex：adapter 优先用 LLM hint，否则走 heuristic
        complex_q = adapter.adapt(
            base_query=base_query,
            chinese_query=original_chinese_query,
            project_description=project_description,
            llm_hints=complex_hints,
        )

        # medium / simple：优先 LLM，否则从 complex 规则推导
        tiers = llm_hints.get(source_id) or {}
        medium_q = (tiers.get("medium") or "").strip()
        simple_q = (tiers.get("simple") or "").strip()
        if not medium_q or not simple_q:
            derived_m, derived_s = _derive_fallback_tiers(source_id, complex_q)
            if not medium_q:
                medium_q = derived_m
            if not simple_q:
                simple_q = derived_s

        # 去重：若相邻层完全相同则清空上层（execute_search 会跳过空串）
        if medium_q and medium_q == complex_q:
            medium_q = ""
        if simple_q and (simple_q == complex_q or simple_q == medium_q):
            simple_q = ""

        adapter_notes = adapter.get_notes()

        if source_id in llm_hints:
            # LLM batch 有明确的 hint → 正常启用
            method = "llm"
            source_enabled = not is_disabled
            plan_notes = adapter_notes
        elif llm_hints_empty:
            # LLM 完全不可用 → 所有源走 fallback，保持 enabled（原行为）
            method = "passthrough" if isinstance(adapter, DefaultAdapter) else "heuristic"
            source_enabled = not is_disabled
            plan_notes = adapter_notes
        else:
            # LLM 部分成功但漏掉此源 → 视为不适合当前主题，默认关闭
            method = "llm_skipped"
            source_enabled = False
            skip_note = "LLM 判定此源不适合当前主题，默认关闭（手动开启则使用 fallback query）"
            plan_notes = f"{skip_note}；{adapter_notes}" if adapter_notes else skip_note

        plans.append(SourceKeywordPlan(
            source_id=source_id,
            display_name=meta.get("name", source_id),
            query=complex_q,
            query_medium=medium_q,
            query_simple=simple_q,
            query_format=adapter.query_format,
            language=meta.get("language", "en"),
            enabled=source_enabled,
            generation_method=method,
            notes=plan_notes,
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
