"""
Research Agent — 协作研究模式的 LLM 大脑（vibe 两阶段版）。

API 分成两个独立方法，便于上层根据 auto/vibe 模式拼装：
- plan(question, candidates, kg_candidates) → {picks, kg_queries}
- respond(question, papers, ..., kg_subgraph) → {answer, citations, note_update?, ...}
"""
import json
import logging
import re
from typing import Dict, List, Optional

from app.harness.prompts.research import (
    build_planning_prompt,
    build_research_prompt,
)
from app.harness.skills.skill_injector import maybe_inject_skill

logger = logging.getLogger(__name__)


class ResearchAgent:
    """Conversational research agent with explicit plan / respond stages."""

    def __init__(self, llm_manager=None, active_skill_id: Optional[str] = None):
        self._llm = llm_manager
        self._active_skill_id = active_skill_id

    # ──────────── Stage 1: planning ────────────

    async def plan(
        self,
        question: str,
        candidates: List[Dict],
        kg_candidates: List[Dict] = None,
        max_reads: int = 3,
        max_kg_queries: int = 5,
    ) -> Dict:
        """
        Ask LLM to decide which papers to fully read and which KG entities to expand.

        Returns:
            {"picks": [{doc_id, reason}], "kg_queries": [{entity, reason}]}
            — 解析失败或 LLM 不可用时返回 {"picks": [], "kg_queries": []}
        """
        if not self._llm or not question.strip() or not candidates:
            return {"picks": [], "kg_queries": []}

        system_prompt, user_prompt = build_planning_prompt(
            question=question,
            candidates=candidates,
            kg_candidates=kg_candidates or [],
            max_reads=max_reads,
            max_kg_queries=max_kg_queries,
        )
        system_prompt, _skill_dbg = await maybe_inject_skill(
            base_system_prompt=system_prompt,
            hook_point="planning",
            explicit_skill_id=self._active_skill_id,
            triggers_seen=[question],
        )
        if _skill_dbg.get("applied"):
            logger.info("[ResearchAgent.plan] skill applied: %s", _skill_dbg["skill_name"])
        combined = f"{system_prompt}\n\n---\n\n{user_prompt}"

        for attempt in range(2):
            try:
                result = await self._llm.generate(
                    combined, temperature=0.2,
                    response_format={"type": "json_object"},
                )
                if not result:
                    if attempt == 0:
                        continue
                    return {"picks": [], "kg_queries": []}
                parsed = _parse_planning_response(result)
                if parsed is not None:
                    picks = _filter_picks(parsed.get("picks", []), candidates, max_reads)
                    queries = _filter_kg_queries(
                        parsed.get("kg_queries", []),
                        kg_candidates or [],
                        max_kg_queries,
                    )
                    logger.info(
                        "[ResearchAgent.plan] picks=%d queries=%d (raw picks=%d queries=%d)",
                        len(picks), len(queries),
                        len(parsed.get("picks", [])),
                        len(parsed.get("kg_queries", [])),
                    )
                    return {"picks": picks, "kg_queries": queries}
                if attempt == 0:
                    logger.warning(
                        "[ResearchAgent.plan] parse failed, retry: %s", result[:150]
                    )
            except Exception as e:
                logger.warning(
                    "[ResearchAgent.plan] error (attempt %d): %s", attempt + 1, e
                )
                if attempt == 0:
                    continue
        return {"picks": [], "kg_queries": []}

    # ──────────── Stage 2: answering ────────────

    async def respond(
        self,
        question: str,
        papers: List[Dict],
        project_description: str,
        user_memory: str = "",
        conversation_history: List[Dict] = None,
        pages: Optional[List[Dict]] = None,
        kg_subgraph: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        Generate the final answer given papers (with selected full_texts injected)
        and an optional KG subgraph.

        Returns:
            {answer, citations, follow_up_suggestions, confidence, note_update?}
            or None on failure.
        """
        if not self._llm or not question.strip():
            return None

        system_prompt, user_prompt = build_research_prompt(
            question=question,
            papers=papers,
            project_description=project_description,
            user_memory=user_memory,
            conversation_history=conversation_history,
            pages=pages,
            kg_subgraph=kg_subgraph,
        )
        system_prompt, _skill_dbg = await maybe_inject_skill(
            base_system_prompt=system_prompt,
            hook_point="collab_respond",
            explicit_skill_id=self._active_skill_id,
            triggers_seen=[question],
        )
        if _skill_dbg.get("applied"):
            logger.info("[ResearchAgent.respond] skill applied: %s", _skill_dbg["skill_name"])
        combined = f"{system_prompt}\n\n---\n\n{user_prompt}"

        for attempt in range(2):
            try:
                # 协作模式答案包含 full_text 节选 + KG 子图 + 笔记 → 长度常超 4096 token 默认
                # 覆盖到 8192 token，基本覆盖所有实际情况。
                # frequency_penalty=0.3：长回答里抑制"车轱辘话"，让综述风格更紧凑。
                result = await self._llm.generate(
                    combined, temperature=0.3, max_tokens=8192,
                    frequency_penalty=0.3,
                )
                if not result:
                    if attempt == 0:
                        continue
                    return None
                parsed = _parse_research_response(result)
                if parsed:
                    nu = parsed.get("note_update")
                    logger.info(
                        "[ResearchAgent.respond] ans=%d cite=%d conf=%.2f note=%s kg_ent=%d",
                        len(parsed.get("answer", "")),
                        len(parsed.get("citations", [])),
                        parsed.get("confidence", 0),
                        nu.get("mode") if nu else "—",
                        len((kg_subgraph or {}).get("entities") or []),
                    )
                    return parsed
                if attempt == 0:
                    logger.warning(
                        "[ResearchAgent.respond] parse failed, retry: %s", result[:150]
                    )
            except Exception as e:
                logger.warning(
                    "[ResearchAgent.respond] error (attempt %d): %s", attempt + 1, e
                )
                if attempt == 0:
                    continue
        return None


# ──────────── filters ────────────

def _filter_picks(
    raw_picks: List[Dict],
    candidates: List[Dict],
    max_reads: int,
) -> List[Dict]:
    valid_ids = {c.get("id") for c in candidates if c.get("has_fulltext")}
    out: List[Dict] = []
    seen = set()
    for pk in raw_picks or []:
        if not isinstance(pk, dict):
            continue
        did = pk.get("doc_id")
        if not isinstance(did, str) or not did or did in seen or did not in valid_ids:
            continue
        seen.add(did)
        out.append({
            "doc_id": did,
            "reason": str(pk.get("reason") or "")[:300],
        })
        if len(out) >= max_reads:
            break
    return out


def _filter_kg_queries(
    raw_queries: List[Dict],
    kg_candidates: List[Dict],
    max_kg_queries: int,
) -> List[Dict]:
    if not kg_candidates:
        return []
    label_lookup = { (c.get("label") or "").strip().lower(): c for c in kg_candidates }
    id_lookup = { c.get("entity_id"): c for c in kg_candidates }
    out: List[Dict] = []
    seen = set()
    for q in raw_queries or []:
        if not isinstance(q, dict):
            continue
        ent = (q.get("entity") or "").strip()
        if not ent:
            continue
        key = ent.lower()
        cand = label_lookup.get(key) or id_lookup.get(ent)
        if not cand or key in seen:
            continue
        seen.add(key)
        out.append({
            "entity": cand.get("label") or ent,
            "entity_id": cand.get("entity_id"),
            "node_type": cand.get("node_type"),
            "reason": str(q.get("reason") or "")[:300],
        })
        if len(out) >= max_kg_queries:
            break
    return out


# ──────────── response parsers ────────────

_VALID_NOTE_MODES = {"create_page", "update_page", "append_to_page"}


def _parse_note_update(raw) -> Optional[Dict]:
    if not isinstance(raw, dict):
        return None
    mode = raw.get("mode")
    if mode not in _VALID_NOTE_MODES:
        return None
    content = raw.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    page_id = raw.get("page_id")
    title = raw.get("title")
    if mode == "create_page":
        if not isinstance(title, str) or not title.strip():
            return None
    if mode in ("update_page", "append_to_page"):
        if not isinstance(page_id, str) or not page_id.strip():
            return None
    reason = raw.get("reason") or ""
    if not isinstance(reason, str):
        reason = str(reason)
    return {
        "mode": mode,
        "page_id": (page_id or "").strip() or None,
        "title": (title or "").strip()[:200] or None,
        "content": content[:10000],
        "reason": reason[:300],
    }


def _parse_research_response(text: str) -> Optional[Dict]:
    match = re.search(r'\{[\s\S]*"answer"[\s\S]*\}', text)
    if not match:
        match = re.search(r'\{[\s\S]+\}', text)
        if not match:
            return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    answer = data.get("answer")
    if not answer or not isinstance(answer, str) or len(answer) < 10:
        return None

    citations = data.get("citations") or []
    if not isinstance(citations, list):
        citations = []
    follow_ups = data.get("follow_up_suggestions") or []
    if not isinstance(follow_ups, list):
        follow_ups = []
    confidence = data.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5

    note_update = _parse_note_update(data.get("note_update"))
    card_updates = _parse_card_updates(data.get("card_updates"))

    out: Dict = {
        # 协作模式带全文节选 + KG 上下文 → 长答案是常态；5000 字符经常被截断
        "answer": answer[:15000],
        "citations": citations[:20],
        "follow_up_suggestions": [str(s)[:200] for s in follow_ups[:5]],
        "confidence": max(0.0, min(1.0, float(confidence))),
    }
    if note_update:
        out["note_update"] = note_update
    if card_updates:
        out["card_updates"] = card_updates
    return out


_VALID_CARD_FIELDS = {"one_line_summary", "ai_summary", "ai_key_points"}


def _parse_card_updates(raw) -> List[Dict]:
    """
    解析 LLM 建议的卡片更新。严格 schema，LLM 产幻觉的字段会被丢弃。
    """
    if not isinstance(raw, list):
        return []
    out: List[Dict] = []
    for item in raw[:5]:  # 硬上限
        if not isinstance(item, dict):
            continue
        did = str(item.get("doc_id") or "").strip()
        field = item.get("field")
        if not did or field not in _VALID_CARD_FIELDS:
            continue
        new_value = item.get("new_value")
        if field == "ai_key_points":
            if not isinstance(new_value, list):
                continue
            new_value = [str(s).strip() for s in new_value if str(s).strip()][:12]
            if not new_value:
                continue
        else:
            if not isinstance(new_value, str):
                new_value = str(new_value) if new_value is not None else ""
            new_value = new_value.strip()
            if not new_value or len(new_value) > 4000:
                continue
        reason = str(item.get("reason") or "").strip()[:400]
        if not reason:
            continue
        out.append({
            "doc_id": did,
            "field": field,
            "new_value": new_value,
            "reason": reason,
        })
        if len(out) >= 2:  # prompt 说本轮最多 2 条
            break
    return out


def _parse_planning_response(text: str) -> Optional[Dict]:
    """
    Parse Stage 1 JSON.
    Returns dict {"picks", "kg_queries"} or None on unparseable. abstain=True → empty lists.
    """
    m = re.search(r'\{[\s\S]+\}', text)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    if data.get("abstain") is True:
        return {"picks": [], "kg_queries": []}
    picks = data.get("picks") or []
    kg_queries = data.get("kg_queries") or []
    if not isinstance(picks, list):
        picks = []
    if not isinstance(kg_queries, list):
        kg_queries = []
    return {"picks": picks, "kg_queries": kg_queries}
