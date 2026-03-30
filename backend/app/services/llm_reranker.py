"""
LLM Reranking 模块
对初筛 top-N 文档用 LLM 做二次排序，提升语义相关性判断。
通过 search_config.enable_llm_rerank 开关控制。
"""
import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_RERANK_DOCS = 20
RERANK_PROMPT_TEMPLATE = """You are an academic relevance assessor. Given a research project description and a list of documents, rate each document's relevance to the project on a scale of 1-10.

## Project Description
{project_description}

## Documents to Assess
{documents_block}

## Instructions
Rate each document 1-10 where:
- 1-3: Not relevant or marginally related
- 4-6: Somewhat relevant, related field but not directly applicable
- 7-8: Highly relevant, directly related to the research topic
- 9-10: Extremely relevant, core reference for this project

Return ONLY a JSON array of objects with "id" (the document number) and "score" (1-10).
Example: [{"id": 1, "score": 8}, {"id": 2, "score": 3}]"""


async def llm_rerank(
    docs: List[Dict],
    project_description: str,
    llm_manager,
    max_docs: int = MAX_RERANK_DOCS,
) -> List[Dict]:
    """
    用 LLM 对 top-N 文档做二次排序。
    返回重排后的文档列表（已更新 _relevance_score）。
    LLM 不可用时返回原列表不变。
    """
    if not docs or not llm_manager:
        return docs

    to_rerank = docs[:max_docs]
    remaining = docs[max_docs:]

    # 构建文档描述块
    doc_lines = []
    for i, doc in enumerate(to_rerank, 1):
        title = doc.get("title", "").strip()[:200]
        abstract = (doc.get("abstract") or "").strip()[:300]
        source = doc.get("source", "")
        doc_type = doc.get("doc_type", "paper")
        line = f"[{i}] ({source}/{doc_type}) {title}"
        if abstract:
            line += f"\n    Abstract: {abstract}"
        doc_lines.append(line)

    documents_block = "\n\n".join(doc_lines)
    prompt = RERANK_PROMPT_TEMPLATE.format(
        project_description=project_description[:500],
        documents_block=documents_block,
    )

    try:
        result = await llm_manager.generate(prompt, temperature=0.1)
        if not result:
            logger.warning("[LLMReranker] LLM 返回空结果，跳过 reranking")
            return docs

        # 解析 LLM 输出的 JSON 评分
        llm_scores = _parse_scores(result, len(to_rerank))
        if not llm_scores:
            logger.warning("[LLMReranker] 无法解析 LLM 评分，跳过 reranking")
            return docs

        # 合并分数：原始 50% + LLM 50%（先计算所有新分数再批量更新，避免部分突变）
        updates = []
        for i, doc in enumerate(to_rerank):
            doc_id = i + 1
            llm_score = llm_scores.get(doc_id, 5.0) / 10.0  # 归一化到 0-1
            original_score = doc.get("_relevance_score", 0.0)
            updates.append((round(llm_score, 4), round(0.5 * original_score + 0.5 * llm_score, 4)))

        for i, doc in enumerate(to_rerank):
            doc["_llm_score"] = updates[i][0]
            doc["_relevance_score"] = updates[i][1]

        # 重排
        to_rerank.sort(key=lambda d: d["_relevance_score"], reverse=True)
        logger.info("[LLMReranker] 完成 %d 篇文档 reranking", len(to_rerank))

        return to_rerank + remaining

    except Exception as e:
        logger.warning("[LLMReranker] reranking 失败: %s", e)
        return docs


def _parse_scores(text: str, expected_count: int) -> Optional[Dict[int, float]]:
    """从 LLM 输出解析评分 JSON"""
    # 尝试找到 JSON 数组
    match = re.search(r'\[.*?\]', text, re.DOTALL)
    if not match:
        return None

    try:
        scores_list = json.loads(match.group())
        if not isinstance(scores_list, list):
            return None

        result = {}
        for item in scores_list:
            if isinstance(item, dict) and "id" in item and "score" in item:
                doc_id = int(item["id"])
                score = float(item["score"])
                if 1 <= doc_id <= expected_count and 1 <= score <= 10:
                    result[doc_id] = score

        return result if result else None

    except (json.JSONDecodeError, ValueError):
        return None
