"""
全量数据源验证脚本
用宽泛查询词逐一测试所有 fetcher，输出可达性 + 返回量 + 错误类型

使用方法：
  # 在 Docker worker 容器中运行（真实网络环境）
  docker-compose exec worker python scripts/test_all_fetchers.py

  # 本地运行（需先 cd backend 并激活 venv）
  python scripts/test_all_fetchers.py
"""
import asyncio
import sys
import os
import time
import traceback

# 确保能导入 app 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ──────────── 测试配置 ────────────
TEST_QUERIES = {
    "broad_en":  "technology innovation",   # 宽泛英文词，所有数据源都能匹配
    "patent_en": "heat transfer material",  # 偏专利领域
    "zh":        "材料 技术",               # 中文数据源用
}

# 每个 fetcher 使用的查询词（source_id → key of TEST_QUERIES）
SOURCE_QUERY_MAP = {
    "openalex_zh": "zh",
}
DEFAULT_QUERY_KEY = "broad_en"

# 每个 fetcher 请求 max_results
MAX_RESULTS = 5

# 宽松超时（覆盖 fetcher 默认值）
FETCH_TIMEOUT_SEC = 35

# 需要 API key 的数据源（若 key 缺失，跳过实测，直接标记为"缺配置"）
REQUIRES_CONFIG = {
    "epo_ops":      ["EPO_CONSUMER_KEY", "EPO_CONSUMER_SECRET"],
    "lens_patent":  ["LENS_API_TOKEN"],
    "patenthub":    ["PATENTHUB_API_TOKEN"],
}

# ─────────────────────────────────

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def _color_count(n: int) -> str:
    if n >= 3:
        return f"{GREEN}{BOLD}{n}篇{RESET}"
    elif n >= 1:
        return f"{YELLOW}{n}篇{RESET}"
    else:
        return f"{RED}0篇{RESET}"


def _check_config(source_id: str) -> tuple[bool, str]:
    """返回 (配置齐全, 缺少的 key)"""
    keys = REQUIRES_CONFIG.get(source_id, [])
    if not keys:
        return True, ""
    missing = [k for k in keys if not os.getenv(k, "").strip()]
    if missing:
        return False, ", ".join(missing)
    return True, ""


async def test_fetcher(source_id: str, fetcher) -> dict:
    """测试单个 fetcher，返回结果 dict"""
    result = {
        "source_id": source_id,
        "status": "unknown",   # ok / config_missing / network_error / empty / exception
        "count": 0,
        "error": "",
        "first_title": "",
        "elapsed": 0.0,
    }

    # 检查配置
    config_ok, missing_msg = _check_config(source_id)
    if not config_ok:
        result["status"] = "config_missing"
        result["error"] = f"缺少配置：{missing_msg}"
        return result

    # 选查询词
    qkey = SOURCE_QUERY_MAP.get(source_id, DEFAULT_QUERY_KEY)
    query = TEST_QUERIES[qkey]

    # 临时覆盖 timeout
    orig_timeout = getattr(fetcher, "DEFAULT_TIMEOUT", None)
    fetcher.DEFAULT_TIMEOUT = FETCH_TIMEOUT_SEC

    t0 = time.time()
    try:
        docs = await fetcher.fetch(query, max_results=MAX_RESULTS, year_from=2020, year_to=2025)
        result["elapsed"] = round(time.time() - t0, 2)
        result["count"] = len(docs)
        if docs:
            result["status"] = "ok"
            result["first_title"] = (docs[0].get("title") or "")[:60]
        else:
            result["status"] = "empty"
    except Exception as e:
        result["elapsed"] = round(time.time() - t0, 2)
        exc_type = type(e).__name__
        exc_msg  = str(e)[:120]
        result["status"] = "network_error" if "connect" in exc_msg.lower() or "timeout" in exc_msg.lower() or "ssl" in exc_msg.lower() else "exception"
        result["error"]  = f"{exc_type}: {exc_msg}"
    finally:
        if orig_timeout is not None:
            fetcher.DEFAULT_TIMEOUT = orig_timeout

    return result


def print_result(r: dict):
    sid = r["source_id"].ljust(20)
    st  = r["status"]
    if st == "ok":
        tag = f"{GREEN}✅ OK{RESET}"
        detail = f"{_color_count(r['count'])}  [{r['elapsed']}s]  {r['first_title']}"
    elif st == "empty":
        tag = f"{YELLOW}⚠  EMPTY{RESET}"
        detail = f"返回0篇 [{r['elapsed']}s]（数据源可达，但无结果）"
    elif st == "config_missing":
        tag = f"{CYAN}🔑 NO_KEY{RESET}"
        detail = r["error"]
    elif st == "network_error":
        tag = f"{RED}❌ NET_ERR{RESET}"
        detail = r["error"]
    else:
        tag = f"{RED}💥 EXCEPT{RESET}"
        detail = r["error"]
    print(f"  {sid} {tag}  {detail}")


async def main():
    print(f"\n{BOLD}{'='*70}")
    print("  ScholarPilot — 全量数据源验证")
    print(f"  查询词: {TEST_QUERIES['broad_en']} / {TEST_QUERIES['zh']}")
    print(f"  max_results={MAX_RESULTS}  timeout={FETCH_TIMEOUT_SEC}s")
    print(f"{'='*70}{RESET}\n")

    # 动态导入（避免在顶层 import 失败导致整个脚本崩溃）
    try:
        from app.services.fetchers.international import (
            PubMedFetcher, OpenAlexFetcher, OpenAlexZhFetcher,
            SemanticScholarFetcher, EuropePMCFetcher, ArXivFetcher,
            BioRxivFetcher, MedRxivFetcher,
        )
        from app.services.fetchers.patents import USPTOFetcher
        from app.services.fetchers.clinical import ClinicalTrialsFetcher
        from app.services.fetchers.crossref import CrossrefFetcher
        from app.services.fetchers.lens import LensPatentFetcher
        from app.services.fetchers.dblp import DBLPFetcher
        from app.services.fetchers.epo import EPOFetcher
        from app.services.fetchers.patenthub import PatentHubFetcher
    except ImportError as e:
        print(f"{RED}导入失败：{e}{RESET}")
        print("请确认在 backend/ 目录下运行，或已激活正确的虚拟环境。")
        sys.exit(1)

    fetchers = [
        ("openalex",        OpenAlexFetcher()),
        ("europe_pmc",      EuropePMCFetcher()),
        ("crossref",        CrossrefFetcher()),
        ("pubmed",          PubMedFetcher()),
        ("arxiv",           ArXivFetcher()),
        ("semantic_scholar",SemanticScholarFetcher()),
        ("biorxiv",         BioRxivFetcher()),
        ("medrxiv",         MedRxivFetcher()),
        ("dblp",            DBLPFetcher()),
        ("openalex_zh",     OpenAlexZhFetcher()),
        ("clinical_trials", ClinicalTrialsFetcher()),
        ("uspto",           USPTOFetcher()),
        ("lens_patent",     LensPatentFetcher()),
        ("epo_ops",         EPOFetcher()),
        ("patenthub",       PatentHubFetcher()),
    ]

    # 将需要 key 的放最后，先快速测可达的
    results = []
    for sid, fetcher in fetchers:
        print(f"  测试 {sid}...", end="", flush=True)
        r = await test_fetcher(sid, fetcher)
        results.append(r)
        # 覆盖行
        print(f"\r", end="")
        print_result(r)

    # ── 汇总 ──────────────────────────────────────────
    print(f"\n{BOLD}{'─'*70}")
    print("  汇总分类")
    print(f"{'─'*70}{RESET}")

    by_status = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r["source_id"])

    category_names = {
        "ok":             f"{GREEN}✅ 正常（有结果）{RESET}",
        "empty":          f"{YELLOW}⚠  可达但0结果（可能查询词/配置问题）{RESET}",
        "config_missing": f"{CYAN}🔑 缺少 API Key/Cookie{RESET}",
        "network_error":  f"{RED}❌ 网络不可达（封锁/超时）{RESET}",
        "exception":      f"{RED}💥 代码/接口异常{RESET}",
    }
    for status, label in category_names.items():
        srcs = by_status.get(status, [])
        if srcs:
            print(f"  {label}：{', '.join(srcs)}")

    print(f"\n{BOLD}{'='*70}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
