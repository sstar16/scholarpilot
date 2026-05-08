"""
相关度评分引擎
Phase 1: 关键词匹配 + 引用影响力 + 时效性综合评分
"""
import logging
import math
import re
from datetime import date
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "the", "a", "an", "and", "or", "in", "of", "to", "for", "with", "is", "are", "was",
    "that", "this", "been", "have", "has", "had", "not", "but", "from", "can", "will",
    "study", "analysis", "effect", "effects", "patients", "clinical", "trial",
    "based", "using", "results", "method", "methods", "approach", "paper", "article",
    "的", "了", "在", "是", "和", "与", "对", "中", "为", "等", "研究", "分析", "结果",
    "通过", "进行", "提出", "方法", "基于", "本文", "论文",
}

# 学术领域常见同义词/近义词映射
SYNONYM_MAP = {
    "ai": ["artificial intelligence", "machine learning", "deep learning"],
    "artificial intelligence": ["ai", "machine learning"],
    "machine learning": ["ml", "deep learning", "neural network"],
    "deep learning": ["neural network", "cnn", "transformer"],
    "nlp": ["natural language processing", "text mining"],
    "natural language processing": ["nlp", "text mining", "language model"],
    "干细胞": ["stem cell", "stem cells"],
    "stem cell": ["stem cells", "干细胞"],
    "纳米": ["nano", "nanoparticle", "nanomaterial"],
    "nano": ["nanoparticle", "nanomaterial", "纳米"],
    "catalysis": ["catalyst", "catalytic"],
    "catalyst": ["catalysis", "catalytic"],
    "polymer": ["polymeric", "polymerization"],
    "cancer": ["tumor", "tumour", "carcinoma", "oncology"],
    "tumor": ["cancer", "tumour", "carcinoma"],
    "drug": ["pharmaceutical", "medication", "pharmacological"],
    "tobacco": ["cigarette", "nicotine", "smoking"],
    "cigarette": ["tobacco", "nicotine", "smoking"],
    "battery": ["lithium", "electrochemical", "energy storage"],
    "sensor": ["sensing", "detection", "biosensor"],
}

# 默认评分权重（论文/预印本）
DEFAULT_WEIGHTS = {"keyword": 0.60, "citation": 0.25, "recency": 0.15}
# 专利文档权重（citation_count 通常为 0，降低引用权重，提升关键词权重）
PATENT_WEIGHTS = {"keyword": 0.75, "citation": 0.05, "recency": 0.20}


def _expand_with_synonyms(terms: List[str], dynamic_synonyms: Optional[Dict[str, List[str]]] = None) -> List[str]:
    """将查询词扩展为包含同义词的列表，支持动态同义词（LLM 生成）"""
    # 合并静态和动态同义词
    merged_map = dict(SYNONYM_MAP)
    if dynamic_synonyms:
        for k, v in dynamic_synonyms.items():
            if k in merged_map:
                merged_map[k] = list(set(merged_map[k] + v))
            else:
                merged_map[k] = v
    expanded = list(terms)
    for term in terms:
        term_l = term.lower().strip()
        if term_l in merged_map:
            for syn in merged_map[term_l]:
                if syn not in [t.lower() for t in expanded]:
                    expanded.append(syn)
    return expanded


def _compute_batch_idf(docs: List[Dict], terms: List[str]) -> Dict[str, float]:
    """计算当前批次内各词的 IDF 权重（高频通用词降权）"""
    n = len(docs)
    if n == 0:
        return {}
    doc_freq: Dict[str, int] = {}
    for doc in docs:
        text = " ".join(filter(None, [
            doc.get("title", ""),
            doc.get("abstract", ""),
        ])).lower()
        for term in terms:
            term_l = term.lower().strip()
            if term_l and term_l in text:
                doc_freq[term_l] = doc_freq.get(term_l, 0) + 1
    idf = {}
    for term in terms:
        term_l = term.lower().strip()
        df = doc_freq.get(term_l, 0)
        # IDF = log(N / (df + 1)) + 1，确保最低权重为 1.0
        idf[term_l] = math.log(n / (df + 1)) + 1.0 if df < n else 1.0
    return idf


def keyword_score(
    doc: Dict,
    query_terms: List[str],
    exclude_terms: Optional[List[str]] = None,
    idf_weights: Optional[Dict[str, float]] = None,
    dynamic_synonyms: Optional[Dict[str, List[str]]] = None,
) -> float:
    """关键词相关度打分 0.0-1.0，支持同义词扩展（静态+动态）和 IDF 加权"""
    title = doc.get("title", "") or ""
    abstract = doc.get("abstract", "") or ""
    ai_summary = doc.get("ai_summary", "") or ""
    text = f"{title} {abstract} {ai_summary}".lower()
    has_abstract = bool(abstract.strip())

    if not text.strip() or not query_terms:
        return 0.0

    if exclude_terms:
        for excl in exclude_terms:
            if excl.lower() in text:
                score_penalty = True
                break
        else:
            score_penalty = False
    else:
        score_penalty = False

    # 扩展同义词（静态 + 动态）
    expanded = _expand_with_synonyms(query_terms, dynamic_synonyms)

    total_weight = 0.0
    matched_weight = 0.0

    for term in expanded:
        term_l = term.lower().strip()
        if not term_l or term_l in STOP_WORDS:
            continue

        # IDF 加权（高频词降权），与词长权重取较大值
        len_weight = min(len(term_l) / 5.0, 2.0)
        idf_w = idf_weights.get(term_l, 1.5) if idf_weights else 1.5
        weight = max(len_weight, idf_w * 0.8)

        # 同义词扩展的词权重降低（原始查询词全权重）
        is_original = term_l in [t.lower() for t in query_terms]
        if not is_original:
            weight *= 0.5

        total_weight += weight

        if term_l in text:
            matched_weight += weight
        elif len(term_l) > 4:
            # 词干级部分匹配：stem cell → stem cells
            stem = term_l[:max(4, len(term_l) - 2)]
            if stem in text:
                matched_weight += weight * 0.6

    if total_weight == 0:
        return 0.0

    score = matched_weight / total_weight

    # 标题命中加成（标题匹配更有价值）
    title_l = title.lower()
    title_hits = sum(1 for t in query_terms if t.lower() in title_l)
    if title_hits > 0:
        bonus = 1.0 + min(title_hits * 0.15, 0.5)  # 最多 +50%
        score = min(score * bonus, 1.0)

    # 仅有标题无摘要时降权（信息不充分）
    if not has_abstract:
        score *= 0.7

    # 排除词命中：软降权而非归零，保留结果但排在后面
    if score_penalty:
        score *= 0.15

    return round(min(score, 1.0), 4)


def citation_score(citation_count: int, max_citations: int) -> float:
    """对数归一化引用分数 (0-1)"""
    if max_citations <= 0 or citation_count <= 0:
        return 0.0
    return round(min(math.log1p(citation_count) / math.log1p(max_citations), 1.0), 4)


def recency_score(pub_date_str, reference_date: date = None) -> float:
    """时效性分数：近期发表得分更高，30年衰减到0"""
    if not pub_date_str:
        return 0.3
    try:
        if isinstance(pub_date_str, date):
            pub_date = pub_date_str
        else:
            from dateutil import parser as dateparser
            pub_date = dateparser.parse(str(pub_date_str)).date()
        ref = reference_date or date.today()
        age_years = (ref - pub_date).days / 365.25
        if age_years < 0:
            age_years = 0
        return round(max(0.0, 1.0 - age_years / 30.0), 4)
    except Exception:
        return 0.3


def select_top_documents(
    docs: List[Dict],
    query_terms: List[str],
    max_select: int,
    exclude_terms: Optional[List[str]] = None,
    exclude_doc_keys: Optional[Set[str]] = None,
    scoring_weights: Optional[Dict[str, float]] = None,
    min_return: int = 5,
    dynamic_synonyms: Optional[Dict[str, List[str]]] = None,
) -> List[Dict]:
    """对候选文档打分并选出 top-N，支持跨轮去重、综合评分、per-doc-type 自适应权重"""
    base_weights = scoring_weights or DEFAULT_WEIGHTS

    # 跨轮去重：排除已出现过或标为不相关的文档
    if exclude_doc_keys:
        docs = [d for d in docs if f"{d.get('source')}:{d.get('external_id')}" not in exclude_doc_keys]

    if not docs:
        return []

    # exclude_terms 安全阀：如果排除词命中 >80% 文档，忽略排除词
    effective_exclude = exclude_terms
    if exclude_terms:
        excluded_count = 0
        for doc in docs:
            text = " ".join(filter(None, [doc.get("title", ""), doc.get("abstract", "")])).lower()
            if any(excl.lower() in text for excl in exclude_terms):
                excluded_count += 1
        if len(docs) > 0 and excluded_count / len(docs) > 0.8:
            logger.warning("排除词命中率过高(%.0f%%), 已忽略排除词", excluded_count / len(docs) * 100)
            effective_exclude = None

    # 找到最大引用数用于归一化
    max_citations = max((d.get("citation_count", 0) or 0) for d in docs) if docs else 0

    # 计算批次 IDF 权重（含动态同义词）
    idf_weights = _compute_batch_idf(docs, _expand_with_synonyms(query_terms, dynamic_synonyms))

    scored = []
    for idx, doc in enumerate(docs):
        kw = keyword_score(doc, query_terms, effective_exclude, idf_weights=idf_weights,
                           dynamic_synonyms=dynamic_synonyms)
        cite = citation_score(doc.get("citation_count", 0) or 0, max_citations)
        rec = recency_score(doc.get("publication_date"))
        # 专利文档使用专利权重（citation 权重降低，keyword 权重提升）
        doc_type = doc.get("doc_type", "paper")
        if doc_type == "patent":
            weights = PATENT_WEIGHTS
        else:
            weights = base_weights
        w_kw = weights.get("keyword", 0.60)
        w_cite = weights.get("citation", 0.25)
        w_rec = weights.get("recency", 0.15)
        final = round(w_kw * kw + w_cite * cite + w_rec * rec, 4)

        scored.append({**doc, "_relevance_score": final, "_keyword_score": kw, "_citation_score": cite, "_recency_score": rec})

    # 排序：主键为相关度分数，同分时按元数据完整度（tiebreaker）
    scored.sort(key=lambda d: (d["_relevance_score"], _doc_completeness(d)), reverse=True)

    relevant = [d for d in scored if d["_relevance_score"] >= 0.05]
    # 强化 fallback：scored 有文档但 relevant 为空时，至少返回 top-3
    if not relevant and scored:
        relevant = scored[:min(3, len(scored))]
    elif len(relevant) < min(min_return, len(scored)):
        relevant = scored[:min(min_return, len(scored))]
    return relevant[:max_select]


def _doc_completeness(doc: Dict) -> int:
    """文档元数据完整度评分，用于跨源合并时选择最佳版本"""
    score = 0
    if (doc.get("abstract") or "").strip():
        score += 3
    if doc.get("doi"):
        score += 2
    if (doc.get("citation_count") or 0) > 0:
        score += 2
    if doc.get("publication_date"):
        score += 1
    if doc.get("authors"):
        score += 1
    if doc.get("pdf_url"):
        score += 1
    return score


def deduplicate_docs(docs: List[Dict]) -> List[Dict]:
    """基于 (source, external_id)、DOI 和标题相似度去重，保留元数据最完整的版本"""
    seen_ids = set()
    seen_titles: Dict[str, int] = {}  # title_norm → index in result
    seen_dois: Dict[str, int] = {}    # doi → index in result
    result = []

    for doc in docs:
        key = f"{doc.get('source')}:{doc.get('external_id')}"
        title_norm = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', (doc.get("title") or "").lower())[:60]
        doi = (doc.get("doi") or "").strip().lower()

        # 精确 source:external_id 去重
        if key in seen_ids:
            continue

        # DOI 去重：同一 DOI 的文档合并为最完整版本
        if doi and doi in seen_dois:
            existing_idx = seen_dois[doi]
            if _doc_completeness(doc) > _doc_completeness(result[existing_idx]):
                old_key = f"{result[existing_idx].get('source')}:{result[existing_idx].get('external_id')}"
                seen_ids.discard(old_key)
                result[existing_idx] = doc
            seen_ids.add(key)
            continue

        # 标题相似度去重
        if title_norm and title_norm in seen_titles:
            existing_idx = seen_titles[title_norm]
            if _doc_completeness(doc) > _doc_completeness(result[existing_idx]):
                old_key = f"{result[existing_idx].get('source')}:{result[existing_idx].get('external_id')}"
                seen_ids.discard(old_key)
                result[existing_idx] = doc
            seen_ids.add(key)
            continue

        # 新文档
        idx = len(result)
        seen_ids.add(key)
        if title_norm:
            seen_titles[title_norm] = idx
        if doi:
            seen_dois[doi] = idx
        result.append(doc)

    return result
