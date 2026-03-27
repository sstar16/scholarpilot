"""
相关度评分引擎
Phase 1: 纯关键词匹配打分（继承 v1 逻辑）
Phase 2: + embedding cosine similarity
"""
import re
from typing import Dict, List, Optional

STOP_WORDS = {
    "the", "a", "an", "and", "or", "in", "of", "to", "for", "with", "is", "are", "was",
    "study", "analysis", "effect", "effects", "patients", "clinical", "trial",
    "的", "了", "在", "是", "和", "与", "对", "中", "为", "等", "研究", "分析", "结果",
}


def keyword_score(
    doc: Dict,
    query_terms: List[str],
    exclude_terms: Optional[List[str]] = None,
) -> float:
    """
    关键词相关度打分 0.0-1.0
    继承自 v1 relevance_scorer.py 的匹配算法
    """
    text = " ".join(filter(None, [
        doc.get("title", ""),
        doc.get("abstract", ""),
        doc.get("ai_summary", ""),
    ])).lower()

    if not text or not query_terms:
        return 0.0

    # 排除词命中直接降分
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
        # 较长的词权重更高
        weight = min(len(term_l) / 5.0, 2.0)
        total_weight += weight
        if term_l in text:
            matched_weight += weight
        elif len(term_l) > 4 and text[:len(term_l)] == term_l[:len(text[:len(term_l)])]:
            matched_weight += weight * 0.5

    if total_weight == 0:
        return 0.0

    score = matched_weight / total_weight
    # 标题命中加权
    title = doc.get("title", "").lower()
    title_hits = sum(1 for t in query_terms if t.lower() in title)
    if title_hits > 0:
        score = min(score * 1.3, 1.0)

    return round(min(score, 1.0), 4)


def select_top_documents(
    docs: List[Dict],
    query_terms: List[str],
    max_select: int,
    exclude_terms: Optional[List[str]] = None,
) -> List[Dict]:
    """对候选文档打分并选出 top-N"""
    scored = []
    for doc in docs:
        score = keyword_score(doc, query_terms, exclude_terms)
        scored.append({**doc, "_relevance_score": score})

    # 按分数降序，同分按引用数降序
    scored.sort(key=lambda d: (d["_relevance_score"], d.get("citation_count", 0)), reverse=True)

    # 过滤极低分（<0.05）
    relevant = [d for d in scored if d["_relevance_score"] >= 0.05]
    print(f"[RelevanceEngine] 候选{len(scored)}篇, 过滤后{len(relevant)}篇, 分数分布: {[d['_relevance_score'] for d in scored[:5]]}")
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
