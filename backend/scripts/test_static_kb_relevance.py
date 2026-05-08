"""
Static DB 检索质量测试 — BM25 baseline vs. ScoringAgent re-rank

运行方式：
    docker-compose exec backend python scripts/test_static_kb_relevance.py

覆盖 3 个真实 query：
1. 锂电池正极材料（英文论文为主）
2. CRISPR 基因编辑（生物医学 + 专利）
3. 卷烟香味稳定性（交叉学科，混合文献）
"""
import asyncio
import sys
import time

sys.path.insert(0, "/app")

from app.knowledge_base.fetcher import LocalKBFetcher
from app.harness.agents.scoring_agent import ScoringAgent
from app.services.core.llm_config_store import get_llm_manager


TEST_CASES = [
    {
        "name": "锂电池正极材料",
        "query": "lithium iron phosphate cathode",
        "year_from": 2019,
        "year_to": 2024,
        "project_description": "研究磷酸铁锂 (LiFePO4) 电池正极材料的制备工艺、掺杂改性和循环寿命优化，关注能量密度和倍率性能提升",
    },
    {
        "name": "CRISPR 基因编辑",
        "query": "CRISPR Cas9 gene editing therapy",
        "year_from": 2020,
        "year_to": 2024,
        "project_description": "研究 CRISPR-Cas9 基因编辑技术在人类遗传病治疗中的临床应用，关注递送系统和脱靶效应控制",
    },
    {
        "name": "卷烟香味稳定性",
        "query": "tobacco flavor encapsulation release kinetics",
        "year_from": 2019,
        "year_to": 2024,
        "project_description": "研究卷烟中香精香料的微胶囊包埋工艺和可控释放动力学，提升烟气风味稳定性",
    },
]


def _short(text: str, n: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "..."


async def run_case(case, fetcher: LocalKBFetcher, scoring: ScoringAgent):
    print("\n" + "=" * 78)
    print(f"▶ 测试: {case['name']}")
    print(f"  query      = {case['query']}")
    print(f"  year_range = {case['year_from']}-{case['year_to']}")
    print(f"  project    = {case['project_description']}")
    print("=" * 78)

    # Step 1: BM25 召回
    t0 = time.time()
    docs = await fetcher.fetch(
        query=case["query"],
        max_results=30,
        year_from=case["year_from"],
        year_to=case["year_to"],
    )
    bm25_ms = int((time.time() - t0) * 1000)
    print(f"\n[BM25] 召回 {len(docs)} 篇 ({bm25_ms}ms)")
    if not docs:
        print("  (零结果)")
        return

    print("Top 5 (BM25 ranking):")
    for i, d in enumerate(docs[:5], 1):
        title = _short(d.get("title") or "", 75)
        dt = d.get("doc_type") or "?"
        date = (d.get("publication_date") or "?")[:10]
        journal = _short(d.get("journal") or "", 35)
        print(f"  {i}. [{dt}] {title}")
        print(f"     {date} | {journal}")

    # Step 2: LLM re-rank
    t0 = time.time()
    above, below = await scoring.score_all(
        docs=docs,
        project_description=case["project_description"],
        cutoff=7.0,
    )
    rerank_ms = int((time.time() - t0) * 1000)
    print(f"\n[ScoringAgent] {rerank_ms}ms — above={len(above)} below={len(below)}")
    print("Top 5 (LLM re-ranked):")
    for i, d in enumerate(above[:5], 1):
        score = d.get("_agent_score") or 0
        title = _short(d.get("title") or "", 75)
        one = _short(d.get("_one_line_summary") or "", 90)
        print(f"  {i}. [{score:>4.1f}/10] {title}")
        if one:
            print(f"              → {one}")

    # 相关性汇总
    high = sum(1 for d in above if (d.get("_agent_score") or 0) >= 8.0)
    mid = sum(1 for d in above if 7.0 <= (d.get("_agent_score") or 0) < 8.0)
    low = sum(1 for d in below if (d.get("_agent_score") or 0) < 7.0)
    print(f"\n分布：high(≥8)={high}  mid(7~8)={mid}  low(<7)={low}")


async def main():
    print("Static DB 检索质量测试")
    print("=" * 78)

    fetcher = LocalKBFetcher()
    if not fetcher.is_available():
        print("本地知识库不可用（search.sqlite 不存在）")
        sys.exit(1)

    fetcher._ensure_loaded()
    total_docs = fetcher._search.count() if fetcher._search else 0
    print(f"本地知识库总量: {total_docs:,} 篇")

    llm = await get_llm_manager()
    if not llm:
        print("LLM manager 不可用，无法测试 ScoringAgent")
        sys.exit(1)

    scoring = ScoringAgent(llm_manager=llm)

    for case in TEST_CASES:
        try:
            await run_case(case, fetcher, scoring)
        except Exception as e:
            print(f"case {case['name']} 失败: {e}")
            import traceback
            traceback.print_exc()

    fetcher.close()
    print("\n" + "=" * 78)
    print("全部测试完成")


if __name__ == "__main__":
    asyncio.run(main())
