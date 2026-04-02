"""
Scoring Agent — LLM 逐篇评分，替代硬编码的 relevance_engine 公式。

设计原则：
1. 逐篇评分（非批量），每篇文献获得 agent 完整注意力
2. asyncio.gather 并行调用，总延迟 ≈ 单篇延迟
3. Agent 分数即最终分数，传统分数仅在 LLM 完全不可用时 fallback
4. 成本不是瓶颈，性能（准确性）优先
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.harness.prompts.scoring import build_scoring_prompt

logger = logging.getLogger(__name__)

# Semaphore to limit concurrent LLM calls (avoid overwhelming API)
_MAX_CONCURRENT_SCORING = 10


@dataclass
class ScoredDoc:
    """单篇文档的评分结果"""
    doc: Dict
    agent_score: Optional[float] = None
    rationale: str = ""
    one_line_summary: str = ""
    below_cutoff: bool = False
    scoring_failed: bool = False


class ScoringAgent:
    """
    LLM-based document scoring agent.
    对每篇文献独立调用 LLM 评分，并行执行。
    """

    def __init__(self, llm_manager=None, max_concurrent: int = _MAX_CONCURRENT_SCORING):
        self._llm = llm_manager
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def score_single(
        self,
        doc: Dict,
        project_description: str,
        user_memory: str = "",
    ) -> ScoredDoc:
        """
        评分单篇文档。
        失败时 scoring_failed=True，调用方可用传统分数作 fallback。
        """
        if not self._llm:
            return ScoredDoc(doc=doc, scoring_failed=True)

        system_prompt, user_prompt = build_scoring_prompt(
            project_description=project_description,
            doc=doc,
            user_memory=user_memory,
        )

        # 合并为单个 prompt（因为 generate() 接口只接受单字符串）
        combined_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

        async with self._semaphore:
            # 尝试最多 2 次
            for attempt in range(2):
                try:
                    result = await self._llm.generate(combined_prompt, temperature=0.15)
                    if not result:
                        if attempt == 0:
                            continue
                        return ScoredDoc(doc=doc, scoring_failed=True)

                    parsed = _parse_scoring_response(result)
                    if parsed:
                        return ScoredDoc(
                            doc=doc,
                            agent_score=parsed["score"],
                            rationale=parsed["rationale"],
                            one_line_summary=parsed["one_line"],
                        )

                    if attempt == 0:
                        logger.warning(
                            "[ScoringAgent] 解析失败，重试: %s → %s",
                            doc.get("title", "")[:50],
                            result[:100],
                        )
                        continue

                except Exception as e:
                    logger.warning(
                        "[ScoringAgent] 评分异常 (attempt %d): %s — %s",
                        attempt + 1, doc.get("title", "")[:50], e,
                    )
                    if attempt == 0:
                        continue

        return ScoredDoc(doc=doc, scoring_failed=True)

    async def score_all(
        self,
        docs: List[Dict],
        project_description: str,
        cutoff: float = 7.0,
        user_memory: str = "",
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        并行评分所有文档，按 cutoff 分为 above/below 两组。

        Returns:
            (above_cutoff_docs, below_cutoff_docs)
            每篇 doc dict 中注入：
              _agent_score, _agent_rationale, _one_line_summary, _below_cutoff
        """
        if not docs:
            return [], []

        if not self._llm:
            logger.warning("[ScoringAgent] LLM 不可用，所有文档使用传统分数 fallback")
            return _fallback_all(docs, cutoff)

        # 并行评分
        tasks = [
            self.score_single(doc, project_description, user_memory)
            for doc in docs
        ]
        results: List[ScoredDoc] = await asyncio.gather(*tasks)

        above = []
        below = []
        scored_count = 0
        fallback_count = 0

        for scored in results:
            doc = scored.doc

            if scored.scoring_failed:
                # Fallback: 用传统分数 × 10
                fallback_count += 1
                traditional = doc.get("_relevance_score", 0.5)
                agent_score = round(traditional * 10, 1)
                doc["_agent_score"] = agent_score
                doc["_agent_rationale"] = "（LLM评分失败，使用传统分数）"
                doc["_one_line_summary"] = ""
            else:
                scored_count += 1
                doc["_agent_score"] = scored.agent_score
                doc["_agent_rationale"] = scored.rationale
                doc["_one_line_summary"] = scored.one_line_summary

            is_below = doc["_agent_score"] < cutoff
            doc["_below_cutoff"] = is_below

            if is_below:
                below.append(doc)
            else:
                above.append(doc)

        # 按 agent_score 降序排列
        above.sort(key=lambda d: d.get("_agent_score", 0), reverse=True)
        below.sort(key=lambda d: d.get("_agent_score", 0), reverse=True)

        logger.info(
            "[ScoringAgent] 评分完成: %d 篇成功, %d 篇 fallback, "
            "%d 篇过线 (cutoff=%.1f), %d 篇淘汰",
            scored_count, fallback_count, len(above), cutoff, len(below),
        )

        # 保底：如果所有文档都在斩杀线以下，至少返回 top-3
        if not above and below:
            logger.warning("[ScoringAgent] 所有文档低于斩杀线，保底返回 top-3")
            rescue = below[:3]
            for d in rescue:
                d["_below_cutoff"] = False
            above = rescue
            below = below[3:]

        return above, below


def _fallback_all(
    docs: List[Dict], cutoff: float
) -> Tuple[List[Dict], List[Dict]]:
    """LLM 完全不可用时的 fallback：传统分数 × 10"""
    above, below = [], []
    for doc in docs:
        traditional = doc.get("_relevance_score", 0.5)
        score = round(traditional * 10, 1)
        doc["_agent_score"] = score
        doc["_agent_rationale"] = "（LLM不可用，使用传统评分）"
        doc["_one_line_summary"] = ""
        doc["_below_cutoff"] = score < cutoff
        if score < cutoff:
            below.append(doc)
        else:
            above.append(doc)
    above.sort(key=lambda d: d.get("_agent_score", 0), reverse=True)
    below.sort(key=lambda d: d.get("_agent_score", 0), reverse=True)
    if not above and below:
        above = below[:3]
        for d in above:
            d["_below_cutoff"] = False
        below = below[3:]
    return above, below


def _parse_scoring_response(text: str) -> Optional[Dict]:
    """
    从 LLM 输出解析评分 JSON。
    支持格式：{"score": 8.5, "rationale": "...", "one_line": "..."}
    """
    # 尝试找 JSON 对象
    match = re.search(r'\{[^{}]*"score"[^{}]*\}', text, re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    score = data.get("score")
    if score is None:
        return None

    try:
        score = float(score)
    except (TypeError, ValueError):
        return None

    if not (0 <= score <= 10):
        return None

    return {
        "score": round(score, 1),
        "rationale": str(data.get("rationale", ""))[:200],
        "one_line": str(data.get("one_line", ""))[:100],
    }
