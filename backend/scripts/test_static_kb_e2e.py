"""
Static DB 端到端管线测试 — 完整走 ResearchDecisionAgent → LLM per-source → FTS5 → ScoringAgent

与 test_static_kb_relevance.py 的区别：
- 该脚本吃**自然语言**，不再手工指定 query/year_range
- 完整调用 ResearchDecisionAgent 生成 QueryPlan（包括年份）
- 调用 generate_all_keywords 让 LLM 按 local_kb.md 规则优化
- 再走 LocalKBFetcher 和 ScoringAgent

运行：
    docker cp backend/scripts/test_static_kb_e2e.py scholarpilot-dev-backend-1:/tmp/
    docker-compose exec -T backend python /tmp/test_static_kb_e2e.py
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, "/app")

from app.harness.agents.research_decision_agent import ResearchDecisionAgent
from app.harness.agents.scoring_agent import ScoringAgent
from app.knowledge_base.fetcher import LocalKBFetcher
from app.services.core.llm_config_store import get_llm_manager
from app.services.source_query_adapters import generate_all_keywords


USER_INPUT = """1. 解决香料容易在卷烟没有使用的时候的保存问题，及随着存放时间逐渐衰减。通常卷烟货架期是 1 年。
    1. 香料使用在卷烟的非燃烧部位，举例滤棒中使用。
2. 解决抽吸前几口香气强烈，后几口衰减明显的问题。
3. 目前市场需求要有明显的香气特征，如何能在抽吸的时候大量释放。
4. 香气特征如何能在烟气中表现出来，甚至能明显盖过烟气。"""


def _short(text: str, n: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "..."


async def main():
    print("=" * 80)
    print("Static DB 端到端管线测试")
    print("=" * 80)
    print("\n【用户输入】")
    print(USER_INPUT)

    # Step 0: LLM manager
    llm = await get_llm_manager()
    if not llm:
        print("\nLLM manager 不可用")
        sys.exit(1)

    # Step 1: ResearchDecisionAgent — 自然语言 → QueryPlan
    print("\n" + "-" * 80)
    print("Step 1: ResearchDecisionAgent 解析自然语言")
    print("-" * 80)
    t0 = time.time()
    decision_agent = ResearchDecisionAgent(llm_manager=llm)
    decision = await decision_agent.decide(user_input=USER_INPUT)
    dt1 = int((time.time() - t0) * 1000)

    if not decision:
        print("ResearchDecisionAgent 返回 None")
        sys.exit(1)

    print(f"({dt1}ms)")
    print(f"  is_research_request: {decision.get('is_research_request')}")
    print(f"  title              : {decision.get('title')}")
    print(f"  description        : {_short(decision.get('description') or '', 120)}")
    print(f"  domains            : {decision.get('domains')}")

    qp = decision.get("query_plan") or {}
    print("  query_plan:")
    print(f"    base_query        : {qp.get('base_query')}")
    print(f"    chinese_query     : {qp.get('chinese_query') or qp.get('original_chinese_query')}")
    print(f"    year_from/year_to : {qp.get('year_from')} / {qp.get('year_to')}")
    print(f"    sources           : {qp.get('sources')}")
    print(f"    language_scope    : {qp.get('language_scope')}")
    print(f"    rationale         : {_short(qp.get('rationale') or '', 120)}")

    base_query = qp.get("base_query") or ""
    chinese_query = qp.get("chinese_query") or qp.get("original_chinese_query") or ""
    year_from = qp.get("year_from")
    year_to = qp.get("year_to")

    if not base_query and not chinese_query:
        print("QueryPlan 为空，终止")
        sys.exit(1)

    # Step 2: LLM per-source 优化（local_kb 专用规则）
    print("\n" + "-" * 80)
    print("Step 2: generate_all_keywords（按 local_kb.md 规则优化）")
    print("-" * 80)
    t0 = time.time()
    kw_result = await generate_all_keywords(
        round_id="test-e2e",
        base_query=base_query,
        original_chinese_query=chinese_query,
        project_description=decision.get("description") or USER_INPUT,
        sources=["local_kb"],
        llm_manager=llm,
        disabled_sources=set(),
    )
    dt2 = int((time.time() - t0) * 1000)
    print(f"({dt2}ms)")
    source_plans = kw_result.source_plans if hasattr(kw_result, "source_plans") else []
    for p in source_plans:
        sid = p.get("source_id") if isinstance(p, dict) else getattr(p, "source_id", None)
        pq = p.get("query") if isinstance(p, dict) else getattr(p, "query", None)
        enabled = p.get("enabled") if isinstance(p, dict) else getattr(p, "enabled", True)
        notes = p.get("notes") if isinstance(p, dict) else getattr(p, "notes", "")
        print(f"  [{sid}] enabled={enabled}")
        print(f"    query: {pq}")
        if notes:
            print(f"    notes: {_short(notes, 150)}")

    local_kb_query = None
    for p in source_plans:
        sid = p.get("source_id") if isinstance(p, dict) else getattr(p, "source_id", None)
        if sid == "local_kb":
            local_kb_query = p.get("query") if isinstance(p, dict) else getattr(p, "query", None)
            break

    if not local_kb_query:
        print("local_kb 未获得 query，终止")
        sys.exit(1)

    # Step 3: LocalKBFetcher — 真·FTS5 检索
    print("\n" + "-" * 80)
    print("Step 3: LocalKBFetcher.fetch() → FTS5")
    print("-" * 80)
    fetcher = LocalKBFetcher()
    if not fetcher.is_available():
        print("本地知识库不可用")
        sys.exit(1)

    fetcher._ensure_loaded()
    total_docs = fetcher._search.count() if fetcher._search else 0
    print(f"  本地库总量: {total_docs:,} 篇")

    t0 = time.time()
    docs = await fetcher.fetch(
        query=local_kb_query,
        max_results=30,
        year_from=year_from,
        year_to=year_to,
    )
    dt3 = int((time.time() - t0) * 1000)
    print(f"  BM25 返回 {len(docs)} 篇 ({dt3}ms)")
    print("\n  Top 5 (BM25 ranking):")
    for i, d in enumerate(docs[:5], 1):
        title = _short(d.get("title") or "", 75)
        dt = d.get("doc_type") or "?"
        date = (d.get("publication_date") or "?")[:10]
        journal = _short(d.get("journal") or "", 35)
        print(f"    {i}. [{dt}] {title}")
        print(f"       {date} | {journal}")

    if not docs:
        print("\n  (BM25 零结果，终止)")
        fetcher.close()
        return

    # Step 4: ScoringAgent 精排
    print("\n" + "-" * 80)
    print("Step 4: ScoringAgent LLM 精排")
    print("-" * 80)
    scoring = ScoringAgent(llm_manager=llm)
    t0 = time.time()
    project_desc = f"【{decision.get('title') or '研究项目'}】{decision.get('description') or USER_INPUT}"
    above, below = await scoring.score_all(
        docs=docs,
        project_description=project_desc,
        cutoff=7.0,
    )
    dt4 = int((time.time() - t0) * 1000)
    print(f"  ({dt4}ms)  above={len(above)}  below={len(below)}")

    high = sum(1 for d in above if (d.get("_agent_score") or 0) >= 8.0)
    mid = sum(1 for d in above if 7.0 <= (d.get("_agent_score") or 0) < 8.0)
    print(f"  分布: ≥8分={high}  7-8分={mid}  <7分={len(below)}")

    print("\n  Top 10 (LLM 精排后):")
    for i, d in enumerate(above[:10], 1):
        score = d.get("_agent_score") or 0
        title = _short(d.get("title") or "", 75)
        dt = d.get("doc_type") or "?"
        date = (d.get("publication_date") or "?")[:10]
        one = _short(d.get("_one_line_summary") or "", 110)
        print(f"    {i:>2}. [{score:>4.1f}/10] [{dt}] {title}")
        print(f"         {date}")
        if one:
            print(f"         → {one}")

    # 汇总
    print("\n" + "=" * 80)
    print("全链路耗时统计")
    print("=" * 80)
    print(f"  ResearchDecisionAgent  : {dt1:>6}ms")
    print(f"  generate_all_keywords  : {dt2:>6}ms")
    print(f"  LocalKBFetcher + FTS5  : {dt3:>6}ms")
    print(f"  ScoringAgent re-rank   : {dt4:>6}ms")
    print(f"  总耗时                 : {dt1+dt2+dt3+dt4:>6}ms")
    fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
