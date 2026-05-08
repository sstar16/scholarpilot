"""
2026-04-21：全数据源连通性交叉测试
- 每个源都用英文 'lithium battery' 和中文 '锂电池' 各测一次
- openalex_zh 额外再测一次 dual 格式
- 年份 2020-2026, max_results=5
- 0 结果或异常 → 重试最多 3 次
"""
import asyncio
import time

from app.services.fetchers.international import ALL_FETCHERS
from app.services.fetchers.base import FetcherRegistry


EN_QUERY = "lithium battery"
ZH_QUERY = "锂电池"
DUAL_QUERY = f"{ZH_QUERY}|||{EN_QUERY}"
YEAR_FROM = 2020
YEAR_TO = 2026
MAX_RESULTS = 5
MAX_RETRIES = 3
RETRY_DELAY = 1.5


async def _one_shot(fetcher, query) -> dict:
    t0 = time.time()
    try:
        result = await fetcher.safe_fetch(
            query=query,
            max_results=MAX_RESULTS,
            year_from=YEAR_FROM,
            year_to=YEAR_TO,
        )
        elapsed = int((time.time() - t0) * 1000)
        try:
            _, docs = result
            count = len(docs) if docs else 0
        except Exception:
            count = 0
            docs = []
        sample = (docs[0].get("title") or "") if docs else ""
        return {"ok": count > 0, "count": count, "elapsed_ms": elapsed,
                "sample": sample[:70], "error": None}
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        return {"ok": False, "count": 0, "elapsed_ms": elapsed,
                "sample": "", "error": f"{type(e).__name__}: {str(e)[:140]}"}


async def test_source(sid, lang_label, query) -> dict:
    fetcher = ALL_FETCHERS.get(sid)
    if not fetcher:
        return {"sid": sid, "lang": lang_label, "query": query,
                "status": "no_fetcher", "attempts": []}

    attempts = []
    for i in range(1, MAX_RETRIES + 1):
        r = await _one_shot(fetcher, query)
        attempts.append(r)
        if r["ok"]:
            return {"sid": sid, "lang": lang_label, "query": query, "status": "ok",
                    "count": r["count"], "ms": r["elapsed_ms"],
                    "sample": r["sample"], "attempts": attempts}
        if i < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAY)
    return {"sid": sid, "lang": lang_label, "query": query,
            "status": "zero" if attempts[-1]["error"] is None else "error",
            "count": 0, "ms": attempts[-1]["elapsed_ms"],
            "last_error": attempts[-1]["error"], "attempts": attempts}


async def main():
    plan = []  # (sid, lang_label, query)
    for sid in FetcherRegistry.SOURCES:
        if sid not in ALL_FETCHERS or sid == "local_kb":
            continue
        # 每个源英文+中文都测
        plan.append((sid, "EN", EN_QUERY))
        plan.append((sid, "ZH", ZH_QUERY))
        if sid == "openalex_zh":
            plan.append((sid, "DUAL", DUAL_QUERY))

    print(f"=== 交叉测试 {len(plan)} 次 fetch 调用 ===")
    print(f"年份: {YEAR_FROM}-{YEAR_TO}, max_results={MAX_RESULTS}, 重试={MAX_RETRIES} 次\n")

    tasks = [test_source(sid, lang, q) for sid, lang, q in plan]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # 按源分组打印
    by_source: dict[str, list] = {}
    for r in results:
        by_source.setdefault(r["sid"], []).append(r)

    print(f"{'源':<18}{'语种':<6}{'状态':<5}{'篇数':<5}{'耗时':<10}{'样例 / 错误'}")
    print("─" * 115)
    ok_cnt = zero_cnt = err_cnt = 0
    for sid, rows in by_source.items():
        for r in rows:
            status = r["status"]
            if status == "ok":
                tag = "✅"
                detail = r.get("sample") or "(无标题)"
                count = r.get("count", 0)
                ok_cnt += 1
            elif status == "zero":
                tag = "⚠️"
                detail = f"重试 {len(r['attempts'])} 次全 0"
                count = 0
                zero_cnt += 1
            else:
                tag = "❌"
                detail = (r.get("last_error") or "")[:85]
                count = 0
                err_cnt += 1
            ms = f"{r.get('ms', 0)}ms"
            print(f"{sid:<18}{r['lang']:<6}{tag:<5}{count:<5}{ms:<10}{detail}")
        print()  # 空行分隔源

    print("─" * 115)
    print(f"\n汇总: ✅ {ok_cnt} · ⚠️ {zero_cnt} · ❌ {err_cnt}  (总调用 {len(plan)})")


if __name__ == "__main__":
    asyncio.run(main())
