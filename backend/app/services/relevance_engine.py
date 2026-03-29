"""
相关度评分引擎
Phase 1: 关键词匹配 + 引用影响力 + 时效性综合评分
"""
import math
import re
from datetime import date
from typing import Dict, List, Optional, Set

STOP_WORDS = {
    "the", "a", "an", "and", "or", "in", "of", "to", "for", "with", "is", "are", "was",
    "study", "analysis", "effect", "effects", "patients", "clinical", "trial",
    "的", "了", "在", "是", "和", "与", "对", "中", "为", "等", "研究", "分析", "结果",
}

# 默认评分权重
DEFAULT_WEIGHTS = {"keyword": 0.60, "citation": 0.25, "recency": 0.15}


def keyword_score(
    doc: Dict,
    query_terms: List[str],
    exclude_terms: Optional[List[str]] = None,
) -> float:
    """关键词相关度打分 0.0-1.0"""
    text = " ".join(filter(None, [
        doc.get("title", ""),
        doc.get("abstract", ""),
        doc.get("ai_summary", ""),
    ])).lower()

    if not text or not query_terms:
        return 0.0

    if exclude_terms:
        for excl in exclude_terms:
            if excl.lower() in text:
                return 0.0

    total_weight = 0.0
    matched_weight = 0.0

    for term in query_terms:
        term_l = term.lower().strip()
        if not term_l or term_l in STOP_WORDS:
            continue
        weight = min(len(term_l) / 5.0, 2.0)
        total_weight += weight
        if term_l in text:
            matched_weight += weight
        elif len(term_l) > 4 and text[:len(term_l)] == term_l[:len(text[:len(term_l)])]:
            matched_weight += weight * 0.5

    if total_weight == 0:
        return 0.0

    score = matched_weight / total_weight
    title = doc.get("title", "").lower()
    title_hits = sum(1 for t in query_terms if t.lower() in title)
    if title_hits > 0:
        score = min(score * 1.3, 1.0)

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
) -> List[Dict]:
    """对候选文档打分并选出 top-N，支持跨轮去重和综合评分"""
    weights = scoring_weights or DEFAULT_WEIGHTS
    w_kw = weights.get("keyword", 0.60)
    w_cite = weights.get("citation", 0.25)
    w_rec = weights.get("recency", 0.15)

    # 跨轮去重：排除已出现过或标为不相关的文档
    if exclude_doc_keys:
        docs = [d for d in docs if f"{d.get('source')}:{d.get('external_id')}" not in exclude_doc_keys]

    if not docs:
        return []

    # 找到最大引用数用于归一化
    max_citations = max((d.get("citation_count", 0) or 0) for d in docs) if docs else 0

    scored = []
    for doc in docs:
        kw = keyword_score(doc, query_terms, exclude_terms)
        cite = citation_score(doc.get("citation_count", 0) or 0, max_citations)
        rec = recency_score(doc.get("publication_date"))
        final = round(w_kw * kw + w_cite * cite + w_rec * rec, 4)
        scored.append({**doc, "_relevance_score": final, "_keyword_score": kw, "_citation_score": cite, "_recency_score": rec})

    scored.sort(key=lambda d: d["_relevance_score"], reverse=True)

    relevant = [d for d in scored if d["_relevance_score"] >= 0.05]
    if len(relevant) < min(min_return, len(scored)):
        relevant = scored[:min(min_return, len(scored))]
    return relevant[:max_select]


def deduplicate_docs(docs: List[Dict]) -> List[Dict]:
    """基于 (source, external_id) 和标题相似度去重"""
    seen_ids = set()
    seen_titles = set()
    result = []
    for doc in docs:
        key = f"{doc.get('source')}:{doc.get('external_id')}"
        title_norm = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', (doc.get("title") or "").lower())[:60]

        if key in seen_ids or title_norm in seen_titles:
            continue
        seen_ids.add(key)
        if title_norm:
            seen_titles.add(title_norm)
        result.append(doc)
    return result
