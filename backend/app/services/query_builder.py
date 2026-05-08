"""
查询词构建器
基于项目描述 + 用户画像，构建各轮次的实际查询词
支持自定义搜索配置和多领域选源
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


# 默认轮次配置 — 仅保留 years/scope 作为轮次递进语义
# max_results 不再按轮次硬编码，统一走 DEFAULT_MAX_RESULTS，由 Agent/用户覆盖
DEFAULT_ROUND_CONFIGS = {
    1: {"years": 5,  "scope": "chinese_first"},
    2: {"years": 10, "scope": "chinese_first"},
    3: {"years": 20, "scope": "international"},
    4: {"years": None, "scope": "international"},
    5: {"years": None, "scope": "global", "translate_summary": True},
}

# 召回配额默认值（轮次无关，AI/用户可覆盖）
DEFAULT_MAX_RESULTS = 30

# 保留旧名称以兼容 progressive_search.py 的导入
ROUND_CONFIGS = DEFAULT_ROUND_CONFIGS

# 每轮注入的画像词数量（轮次越高画像越成熟，注入越多）
_PROFILE_INJECT_COUNT = {2: 3, 3: 5, 4: 8}  # 5+ 默认 10

# 中文字符检测
_CN_PAT = re.compile(r'[\u4e00-\u9fff]')


@dataclass
class QueryPlan:
    base_query: str
    expanded_terms: List[str]
    exclude_terms: List[str]
    year_from: Optional[int]
    year_to: Optional[int]
    sources: List[str]
    max_results_per_source: int
    language_scope: str  # chinese_first | international | global
    original_chinese_query: Optional[str] = None  # 中文数据源使用的原始中文查询词
    english_query_source: str = "regex"   # "llm" | "regex" — 英文查询词生成路径
    cn_query_source: str = "none"          # "llm" | "regex" | "none" — 中文查询词生成路径
    profile_injected_en: List[str] = field(default_factory=list)  # 注入的英文画像词（排序用）
    profile_injected_zh: List[str] = field(default_factory=list)  # 注入的中文画像词（追加到 cn query）
    profile_query_extension: str = ""     # round>=3 时追加到英文 API 查询词的画像词
    anchor_keywords: List[str] = field(default_factory=list)      # 来自项目描述的锚词（不衰减底色）


def _get_round_config(round_number: int, search_config: Optional[Dict[str, Any]] = None) -> Dict:
    """获取轮次配置，优先使用自定义配置"""
    # 已有 per-round 配置时直接使用
    if search_config and "rounds" in search_config:
        rounds = search_config["rounds"]
        if 0 < round_number <= len(rounds):
            cfg = dict(rounds[round_number - 1])
            # max_results=null 表示"全部"，转为大数
            if cfg.get("max_results") is None:
                cfg["max_results"] = 500
            return cfg

    base = dict(DEFAULT_ROUND_CONFIGS.get(round_number, DEFAULT_ROUND_CONFIGS[3]))
    base.setdefault("max_results", DEFAULT_MAX_RESULTS)
    if not search_config:
        return base

    # 年份策略
    year_strategy = search_config.get("year_strategy", "progressive")
    if year_strategy != "progressive":
        year_map = {"last5": 5, "last10": 10, "last20": 20, "all": None}
        base["years"] = year_map.get(year_strategy, base["years"])

    # 语言优先级
    language_scope = search_config.get("language_scope")
    if language_scope:
        base["scope"] = language_scope

    # 每轮返回数（top_k=None 表示全部）
    if "top_k" in search_config:
        top_k = search_config["top_k"]
        base["max_results"] = top_k if top_k is not None else 500

    return base


def get_max_rounds(search_config: Optional[Dict[str, Any]] = None) -> int:
    """获取最大轮数"""
    if search_config and "rounds" in search_config:
        return len(search_config["rounds"])
    return 5


async def build_query(
    project_description: str,
    project_domain: str,
    round_number: int,
    preferred_keywords: Optional[List[str]] = None,
    excluded_keywords: Optional[List[str]] = None,
    preferred_sources: Optional[List[str]] = None,
    llm_manager=None,
    search_config: Optional[Dict[str, Any]] = None,
    project_domains: Optional[List[str]] = None,
    project_title: Optional[str] = None,
) -> QueryPlan:
    """
    为指定轮次构建查询计划。
    支持自定义搜索配置和多领域。
    project_title 会与 description 合并用于关键词提取（标题通常更精准）。
    """
    from datetime import datetime
    config = _get_round_config(round_number, search_config)

    # 标题 + 描述合并（标题放前面，权重更高）
    full_description = project_description
    if project_title:
        full_description = f"{project_title}。{project_description}"

    # 提取/翻译核心关键词（中英文并行，避免串行 LLM 等待）
    import asyncio as _asyncio
    is_chinese = _is_mostly_chinese(full_description)
    if is_chinese:
        (base_query, english_query_source), (original_chinese_query, cn_query_source) = await _asyncio.gather(
            _get_english_query(full_description, llm_manager),
            _get_chinese_query(full_description, llm_manager),
        )
    else:
        base_query, english_query_source = await _get_english_query(full_description, llm_manager)
        original_chinese_query = None
        cn_query_source = "none"

    base_terms = [t for t in base_query.split() if len(t) > 2]

    # B：锚词 = 来自项目描述的 base_terms（每轮固定存在于 expanded_terms，不随画像漂移）
    anchor_keywords = base_terms
    anchor_en_set = set(anchor_keywords)

    # 画像词按语言分流，注入量随轮次递进
    _inject_count = _PROFILE_INJECT_COUNT.get(round_number, 10)
    extra_en: List[str] = []   # 英文词 → expanded_terms（排序用）
    extra_zh: List[str] = []   # 中文词 → 追加到 original_chinese_query（中文源用）
    if preferred_keywords and round_number > 1:
        for kw in preferred_keywords[:_inject_count]:
            if _CN_PAT.search(kw):
                extra_zh.append(kw)
            else:
                extra_en.append(kw)

    expanded_terms = base_terms + extra_en

    # 中文画像词追加到中文数据源查询词（仅当描述为中文时才有 original_chinese_query）
    if extra_zh and original_chinese_query is not None:
        original_chinese_query = original_chinese_query + " " + " ".join(extra_zh)

    # C：round >= 3 时，优先用"反馈词 ∩ 锚词"做 API 扩展（确认了项目描述方向的词）
    # 交集为空时降级用纯反馈词，保留召回能力
    profile_query_extension = ""
    if round_number >= 3 and extra_en:
        confirmed = [kw for kw in extra_en if kw in anchor_en_set]
        extension_src = confirmed if confirmed else extra_en
        profile_query_extension = " ".join(extension_src[:2])

    exclude_terms = excluded_keywords[:3] if excluded_keywords else []

    current_year = datetime.now().year
    years = config.get("years")
    year_from = (current_year - years) if years else None
    year_to = current_year

    scope = config.get("scope", "international")

    # 多领域选源：取所有领域的并集
    domains = project_domains or ([project_domain] if project_domain else [])
    sources = _select_sources(
        scope, domains, preferred_sources, round_number, search_config,
        has_chinese_desc=original_chinese_query is not None,
    )

    max_results = config.get("max_results", DEFAULT_MAX_RESULTS)
    # 单源模式（如 static_db）不均分，直接给全额
    if len(sources) <= 1:
        max_results_per_source = max_results
    else:
        max_results_per_source = max(10, max_results // len(sources))

    return QueryPlan(
        base_query=base_query,
        expanded_terms=expanded_terms,
        exclude_terms=exclude_terms,
        year_from=year_from,
        year_to=year_to,
        sources=sources,
        max_results_per_source=max_results_per_source,
        language_scope=scope,
        original_chinese_query=original_chinese_query,
        english_query_source=english_query_source,
        cn_query_source=cn_query_source,
        profile_injected_en=extra_en,
        profile_injected_zh=extra_zh,
        profile_query_extension=profile_query_extension,
        anchor_keywords=anchor_keywords,
    )


def _extract_core_query(description: str) -> str:
    """
    从项目描述提取核心查询词（LLM 不可用时的 fallback）。
    用 jieba 做中文分词 + 英文正则，双语言 stopwords 统一来自 common.stopwords。
    （原正则 [\u4e00-\u9fff]{2,} 会把连续中文段当一个 token，现在改用 jieba 真正分词）
    """
    import jieba
    from app.services.common.stopwords import ZH_STOPWORDS, EN_STOPWORDS
    text = description[:500].strip()
    if not text:
        return ""

    meaningful: List[str] = []
    for raw in jieba.cut(text):
        w = raw.strip()
        if len(w) < 2:
            continue
        if re.search(r'[\u4e00-\u9fff]', w):
            # 中文 token
            if w not in ZH_STOPWORDS:
                meaningful.append(w)
        elif w.isalpha() and len(w) >= 3:
            # 英文 token
            if w.lower() not in EN_STOPWORDS:
                meaningful.append(w)
    return " ".join(meaningful[:6]) if meaningful else text[:80]


def _is_mostly_chinese(text: str) -> bool:
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return chinese_chars > len(text) * 0.3


async def _get_english_query(description: str, llm_manager) -> tuple[str, str]:
    """返回 (英文查询词, source: 'llm'|'regex')"""
    if not _is_mostly_chinese(description) or llm_manager is None:
        return _extract_core_query(description), "regex"

    prompt = (
        "You are an expert academic/patent search query generator. "
        "Extract 6-8 DOMAIN-SPECIFIC English keywords from the Chinese research description below. "
        "These keywords will be used to search PubMed, arXiv, OpenAlex, and patent databases.\n\n"
        "CRITICAL RULES:\n"
        "1. Use SPECIFIC technical terms, NOT generic words. "
        "Example: 'solid-state electrolyte' NOT 'battery material'.\n"
        "2. Include industry jargon and precise terminology.\n"
        "3. Mix broad concepts (2-3 words) with narrow terms (1 word).\n"
        "4. Include both academic AND patent-style terminology.\n\n"
        f"Description: {description[:400]}\n\n"
        'Return a JSON object with a "keywords" field (array of 3-5 English search terms). No explanation.\n'
        'Example (format only — DO NOT reuse these words; derive keywords from the Description above): '
        '{"keywords": ["<term-A>", "<term-B>", "<term-C>", "<term-D>", "<term-E>"]}'
    )
    try:
        result = await llm_manager.generate(
            prompt, temperature=0.1,
            response_format={"type": "json_object"},
        )
        if result:
            match = re.search(r'\{.*?\}', result, re.DOTALL)
            if match:
                import json as _json
                data = _json.loads(match.group())
                keywords = data.get("keywords", []) if isinstance(data, dict) else []
                if keywords and isinstance(keywords, list) and len(keywords) >= 2:
                    all_words = []
                    for kw in keywords:
                        all_words.extend(str(kw).split())
                    all_words = [w for w in all_words if len(w) >= 2]
                    if len(all_words) >= 3:
                        query = " ".join(all_words[:8])
                        logger.debug("[QueryBuilder] LLM翻译查询: %s", query[:100])
                        return query, "llm"
                    else:
                        fallback = _extract_core_query(description)
                        combined = " ".join(all_words + fallback.split())
                        logger.warning("[QueryBuilder] LLM翻译词过少(%d)，补充中文核心词: %s", len(all_words), combined[:100])
                        return combined, "llm+regex"
    except Exception as e:
        logger.warning("[QueryBuilder] LLM翻译失败，回退到原始提取: %s", e)

    return _extract_core_query(description), "regex"


async def _get_chinese_query(description: str, llm_manager) -> tuple[str, str]:
    """返回 (中文核心查询词, source: 'llm'|'regex')"""
    if llm_manager is None:
        return _extract_core_query(description), "regex"

    prompt = (
        "你是学术检索专家。"
        "从以下研究描述中提取4-6个最核心的中文学术关键词，用于中文数据库检索。"
        '请以 JSON 对象返回，不要解释。\n\n'
        f"描述：{description[:400]}\n\n"
        '示例输出：{"keywords": ["关键词1", "关键词2", "关键词3"]}'
    )
    try:
        result = await llm_manager.generate(
            prompt, temperature=0.1,
            response_format={"type": "json_object"},
        )
        if result:
            match = re.search(r'\{.*?\}', result, re.DOTALL)
            if match:
                import json as _json
                data = _json.loads(match.group())
                keywords = data.get("keywords", []) if isinstance(data, dict) else []
                if keywords and isinstance(keywords, list) and len(keywords) >= 2:
                    valid = [str(k).strip() for k in keywords if str(k).strip()]
                    if valid:
                        query = " ".join(valid[:6])
                        logger.debug("[QueryBuilder] LLM中文关键词: %s", query[:100])
                        return query, "llm"
    except Exception as e:
        logger.warning("[QueryBuilder] LLM中文提取失败，回退正则: %s", e)

    return _extract_core_query(description), "regex"


# 领域到数据源的映射
# 注：已禁用源（pubmed / clinical_trials / semantic_scholar / uspto）不出现在此处。
# 这是 LLM 不可用时的 fallback 路径；主路径 ResearchDecisionAgent 已接管。
DOMAIN_SOURCE_MAP = {
    "cs": ["arxiv", "dblp"],
    "computer": ["arxiv", "dblp"],
    "ai": ["arxiv", "dblp"],
    "software": ["dblp"],
    "biology": ["biorxiv", "medrxiv", "lens_patent", "epo_ops", "patenthub"],
    "medicine": ["biorxiv", "medrxiv", "lens_patent", "epo_ops", "patenthub"],
    "pharmacology": ["biorxiv", "medrxiv", "lens_patent", "epo_ops", "patenthub"],
    "mechanical": ["arxiv", "lens_patent", "epo_ops", "patenthub"],
    "materials": ["arxiv", "lens_patent", "epo_ops", "patenthub"],
    "physics": ["arxiv", "lens_patent", "epo_ops", "patenthub"],
    "math": ["arxiv"],
    "economics": ["arxiv"],
    "chemistry": ["lens_patent", "epo_ops", "patenthub"],
    "environment": ["lens_patent", "epo_ops", "patenthub"],
}


def _select_sources(
    scope: str,
    domains: List[str],
    preferred_sources: Optional[List[str]],
    round_number: int,
    search_config: Optional[Dict[str, Any]] = None,
    has_chinese_desc: bool = False,
) -> List[str]:
    """根据范围、领域列表和配置选择数据源"""
    import os
    from app.services.source_config_store import _config as _src_cfg
    # 同步读取：优先用已缓存的 Redis 配置，回退 env
    env_disabled = {s.strip() for s in os.getenv("DISABLED_SOURCES", "").split(",") if s.strip()}
    if _src_cfg:
        runtime_disabled = set(_src_cfg.get("disabled_overrides", []))
        runtime_enabled = set(_src_cfg.get("enabled_overrides", []))
        disabled = (env_disabled | runtime_disabled) - runtime_enabled
    else:
        disabled = env_disabled

    # 基础国际来源（openalex 覆盖最广；europe_pmc 生物医学；crossref 跨学科引用）
    # 注：pubmed / semantic_scholar 已被环境禁用，从此列表移除
    base_sources = ["openalex", "europe_pmc", "crossref"]
    sources = [s for s in base_sources if s not in disabled]

    # 根据所有领域补充专用来源（取并集）
    added = set()
    for domain in domains:
        domain_lower = domain.lower()
        for key, domain_sources in DOMAIN_SOURCE_MAP.items():
            if key in domain_lower:
                for src in domain_sources:
                    if src not in disabled and src not in added:
                        added.add(src)
                        sources.append(src)
    # 若无匹配领域，默认加 arxiv
    if not added and "arxiv" not in disabled:
        sources.append("arxiv")

    # chinese_first scope + 中文描述：加入中文专用 OpenAlex（language:zh + 原始中文查询词）
    if scope == "chinese_first" and has_chinese_desc:
        for zh_src in ["openalex_zh"]:
            if zh_src not in sources and zh_src not in disabled:
                sources.append(zh_src)

    # 始终尝试加入专利和临床试验来源
    for extra in ["lens_patent", "epo_ops", "patenthub", "clinical_trials"]:
        if extra not in sources and extra not in disabled:
            sources.append(extra)

    # 兼容旧字段：enable_patents/enable_clinical_trials 明确为 False 时排除
    if search_config:
        if search_config.get("enable_patents") is False and "disabled_sources" not in search_config:
            sources = [s for s in sources if s not in ("lens_patent", "epo_ops", "patenthub", "uspto")]
        if search_config.get("enable_clinical_trials") is False and "disabled_sources" not in search_config:
            sources = [s for s in sources if s != "clinical_trials"]

    # 按 search_config.disabled_sources 做精细过滤（优先级高于旧字段）
    if search_config:
        user_disabled = {s.strip() for s in search_config.get("disabled_sources", []) if s}
        sources = [s for s in sources if s not in user_disabled]

    # 优先使用用户偏好来源
    if preferred_sources and round_number > 1:
        sources = sorted(sources, key=lambda s: 0 if s in preferred_sources else 1)

    return sources
