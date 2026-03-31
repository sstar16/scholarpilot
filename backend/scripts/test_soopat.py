#!/usr/bin/env python3
"""
SooPat Fetcher 独立验证脚本

用法：
  # 宿主机（推荐，网络更好）
  cd D:\\AI\\scholarpilot-dev\\backend
  pip install httpx beautifulsoup4 lxml   # 首次
  python scripts/test_soopat.py --query "锂电池" --save-html

  # Docker 容器内
  docker-compose exec backend python scripts/test_soopat.py --query "锂电池"

环境变量（任选一种鉴权）：
  SOOPAT_EMAIL + SOOPAT_PASSWORD  — 账号密码自动登录
  SOOPAT_COOKIES                  — 手动 Cookie 字符串
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 让 import app.services.fetchers 能找到
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_soopat")


async def run_test(query: str, max_results: int, save_html: bool, year_from: int = None, year_to: int = None):
    from app.services.fetchers.soopat import SooPatFetcher

    fetcher = SooPatFetcher()

    # ---- 诊断：鉴权方式 ----
    has_cred = bool(fetcher._email and fetcher._password)
    has_cookie = bool(fetcher._manual_cookies_str)
    if has_cred:
        logger.info("鉴权方式: 账号密码 (email=%s)", fetcher._email)
    elif has_cookie:
        cookie_count = fetcher._manual_cookies_str.count("=")
        logger.info("鉴权方式: 手动 Cookie (%d 个键值对)", cookie_count)
    else:
        logger.error("未配置鉴权！请设置 SOOPAT_EMAIL+SOOPAT_PASSWORD 或 SOOPAT_COOKIES")
        logger.info("示例: set SOOPAT_COOKIES=\"cookie_name=value; another=value2\"")
        return

    # ---- 执行 fetch ----
    logger.info("=" * 60)
    logger.info("查询: %s | max_results=%d | year=%s~%s",
                query, max_results, year_from or "any", year_to or "any")
    logger.info("=" * 60)

    try:
        results = await fetcher.fetch(
            query=query,
            max_results=max_results,
            year_from=year_from,
            year_to=year_to,
        )
    except Exception as e:
        logger.exception("fetch() 异常: %s", e)
        results = []

    # ---- 保存原始 HTML ----
    if save_html and fetcher._last_html:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"debug_soopat_{ts}.html"
        filepath = Path(__file__).resolve().parent / filename
        filepath.write_text(fetcher._last_html, encoding="utf-8")
        logger.info("原始 HTML 已保存: %s (%.1f KB)", filepath, len(fetcher._last_html) / 1024)
    elif save_html:
        logger.warning("无 HTML 可保存（可能未发出请求或登录失败）")

    # ---- 结果摘要 ----
    logger.info("=" * 60)
    logger.info("共获取 %d 条结果", len(results))
    logger.info("=" * 60)

    if not results:
        logger.warning("0 条结果。可能原因：")
        logger.warning("  1. 鉴权失败（密码错误/Cookie 过期）")
        logger.warning("  2. 触发验证码")
        logger.warning("  3. CSS 选择器不匹配（用 --save-html 查看实际 HTML）")
        logger.warning("  4. 网络不通（检查 DNS/防火墙）")
        return

    for i, doc in enumerate(results, 1):
        title = doc.get("title", "")[:60]
        ext_id = doc.get("external_id", "?")
        has_abstract = "有" if doc.get("abstract") else "无"
        pub_date = doc.get("publication_date") or "未知"
        authors = (doc.get("authors") or "")[:40]
        logger.info(
            "[%d] %s | 专利号=%s | 日期=%s | 摘要=%s | 申请人=%s",
            i, title, ext_id, pub_date, has_abstract, authors,
        )

    # ---- 数据质量统计 ----
    with_abstract = sum(1 for d in results if d.get("abstract"))
    with_date = sum(1 for d in results if d.get("publication_date"))
    with_authors = sum(1 for d in results if d.get("authors"))
    with_url = sum(1 for d in results if d.get("url"))
    logger.info("-" * 60)
    logger.info("数据质量: 摘要=%d/%d  日期=%d/%d  申请人=%d/%d  URL=%d/%d",
                with_abstract, len(results), with_date, len(results),
                with_authors, len(results), with_url, len(results))


def main():
    parser = argparse.ArgumentParser(description="SooPat Fetcher 验证脚本")
    parser.add_argument("--query", default="锂电池", help="搜索关键词（默认: 锂电池）")
    parser.add_argument("--max-results", type=int, default=5, help="最大结果数（默认: 5）")
    parser.add_argument("--save-html", action="store_true", help="保存原始 HTML 到文件")
    parser.add_argument("--year-from", type=int, default=None, help="起始年份")
    parser.add_argument("--year-to", type=int, default=None, help="结束年份")
    args = parser.parse_args()

    # 支持从 .env 文件加载（优先检查 backend/.env，再检查项目根 .env）
    for env_candidate in [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]:
        if env_candidate.exists():
            logger.info("加载 .env: %s", env_candidate)
            for line in env_candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            break

    asyncio.run(run_test(
        query=args.query,
        max_results=args.max_results,
        save_html=args.save_html,
        year_from=args.year_from,
        year_to=args.year_to,
    ))


if __name__ == "__main__":
    main()
