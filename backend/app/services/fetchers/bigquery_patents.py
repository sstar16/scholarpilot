"""
Google BigQuery Patents Public Data Fetcher
基于 patents-public-data 公开数据集，覆盖 ~1500万条中国专利（标题+摘要均有中文）

前置：
1. GCP 项目 + Service Account JSON 密钥
2. pip install google-cloud-bigquery
3. 需代理（googleapis.com 被墙）— 通过 BIGQUERY_PROXY 或 DevTools per-source proxy 配置
"""
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 延迟导入，避免未安装时影响其他 fetcher
_bq_client = None
_bq_available = True


def _get_client():
    """懒加载 BigQuery 客户端（进程级单例）"""
    global _bq_client, _bq_available
    if not _bq_available:
        return None
    if _bq_client is not None:
        return _bq_client

    try:
        # 设置代理（必须在 import google.cloud 之前）
        from app.services.source_config_store import get_proxy_for_source
        proxy = get_proxy_for_source("bigquery_patents")
        if proxy:
            os.environ.setdefault("http_proxy", proxy)
            os.environ.setdefault("https_proxy", proxy)

        from google.cloud import bigquery

        # 凭证路径：环境变量 > DevTools 配置
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        if not cred_path:
            # 尝试从 DevTools 凭证配置读取（存的是 JSON 内容）
            from app.services.source_config_store import _config
            if _config:
                cred_json = _config.get("credential_overrides", {}).get(
                    "bigquery_patents", {}
                ).get("GOOGLE_CREDENTIALS_JSON", "")
                if cred_json:
                    info = json.loads(cred_json)
                    from google.oauth2 import service_account
                    credentials = service_account.Credentials.from_service_account_info(info)
                    _bq_client = bigquery.Client(
                        credentials=credentials, project=info.get("project_id")
                    )
                    logger.info("[BigQuery] 客户端初始化成功（DevTools 凭证）")
                    return _bq_client

        if cred_path and os.path.exists(cred_path):
            _bq_client = bigquery.Client.from_service_account_json(cred_path)
            logger.info("[BigQuery] 客户端初始化成功（JSON 文件: %s）", cred_path)
            return _bq_client

        logger.warning("[BigQuery] 未配置凭证，跳过")
        _bq_available = False
        return None

    except ImportError:
        logger.warning("[BigQuery] google-cloud-bigquery 未安装，跳过")
        _bq_available = False
        return None
    except Exception as e:
        logger.error("[BigQuery] 客户端初始化失败: %s", e)
        _bq_available = False
        return None


# ── Fetcher ──

from app.services.fetchers.base import AbstractFetcher


class BigQueryPatentsFetcher(AbstractFetcher):
    """Google BigQuery 中国专利检索 — 标题+摘要全文搜索"""

    source_id = "bigquery_patents"
    DEFAULT_TIMEOUT = 60.0  # BigQuery 查询较慢

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        import asyncio

        client = _get_client()
        if not client:
            return []

        # BigQuery 是同步 SDK，放到线程池执行
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_fetch, client, query, max_results, year_from, year_to
        )

    def _sync_fetch(
        self, client, query: str, max_results: int,
        year_from: Optional[int], year_to: Optional[int],
    ) -> List[Dict]:
        from google.cloud import bigquery as bq

        # 构建关键词条件：拆分查询词，用 OR 匹配标题和摘要
        keywords = [w.strip() for w in query.split() if w.strip()]
        if not keywords:
            return []

        # 每个关键词匹配标题或摘要
        keyword_conditions = []
        params = []
        for i, kw in enumerate(keywords[:5]):
            param_name = f"kw{i}"
            keyword_conditions.append(
                f"(title_info.text LIKE CONCAT('%', @{param_name}, '%') "
                f"OR abstract_info.text LIKE CONCAT('%', @{param_name}, '%'))"
            )
            params.append(bq.ScalarQueryParameter(param_name, "STRING", kw))

        where_kw = " OR ".join(keyword_conditions)

        # 日期过滤
        date_filter = ""
        if year_from:
            date_filter += f" AND pub.publication_date >= {year_from}0101"
            params.append(bq.ScalarQueryParameter("year_from", "INT64", year_from * 10000 + 101))
        if year_to:
            date_filter += f" AND pub.publication_date <= {year_to}1231"
            params.append(bq.ScalarQueryParameter("year_to", "INT64", year_to * 10000 + 1231))

        limit = min(max_results, 50)

        sql = f"""
        SELECT
          pub.publication_number,
          pub.publication_date,
          pub.filing_date,
          pub.family_id,
          title_info.text AS title_zh,
          abstract_info.text AS abstract_zh,
          pub.inventor_harmonized,
          pub.assignee_harmonized
        FROM
          `patents-public-data.patents.publications` AS pub,
          UNNEST(title_localized) AS title_info,
          UNNEST(abstract_localized) AS abstract_info
        WHERE
          pub.country_code = 'CN'
          AND title_info.language = 'zh'
          AND abstract_info.language = 'zh'
          AND abstract_info.text IS NOT NULL
          AND ({where_kw})
          {date_filter}
        LIMIT {limit}
        """

        job_config = bq.QueryJobConfig(query_parameters=params)

        try:
            job = client.query(sql, job_config=job_config)
            rows = list(job)
            gb = (job.total_bytes_processed or 0) / 1e9
            logger.info("[BigQuery] 查询完成: %d 条结果, 扫描 %.2f GB", len(rows), gb)
        except Exception as e:
            logger.error("[BigQuery] 查询失败: %s", e)
            return []

        results = []
        for row in rows:
            pub_num = row.publication_number or ""
            pub_date = self._format_date(row.publication_date)

            # 发明人 / 申请人
            inventors = self._extract_names(row.inventor_harmonized)
            assignees = self._extract_names(row.assignee_harmonized)
            authors = inventors or assignees

            results.append({
                "source": "bigquery_patents",
                "external_id": pub_num,
                "doc_type": "patent",
                "title": row.title_zh or pub_num,
                "authors": authors,
                "abstract": row.abstract_zh,
                "publication_date": pub_date,
                "journal": "CN Patent",
                "doi": None,
                "citation_count": 0,
                "pdf_url": None,
                "url": f"https://patents.google.com/patent/{pub_num.replace('-', '')}",
            })

        return results

    @staticmethod
    def _format_date(date_int) -> Optional[str]:
        """将 BigQuery 日期整数 20230101 转为 '2023-01-01'"""
        if not date_int:
            return None
        s = str(date_int)
        if len(s) >= 8:
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s

    @staticmethod
    def _extract_names(harmonized) -> str:
        """从 inventor_harmonized / assignee_harmonized 提取名称"""
        if not harmonized:
            return ""
        names = []
        items = harmonized if isinstance(harmonized, list) else [harmonized]
        for item in items[:5]:
            if isinstance(item, dict):
                name = item.get("name", "")
            elif isinstance(item, str):
                name = item
            else:
                continue
            if name:
                names.append(name)
        if len(items) > 5:
            names.append("et al.")
        return ", ".join(names)
