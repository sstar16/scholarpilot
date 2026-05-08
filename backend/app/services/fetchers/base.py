"""
AbstractFetcher 基类
继承自 v1 的 _safe_fetch + asyncio.gather 模式

2026-04-27 性能/稳定性改造（curl 调研启发）：
1. ``_http_client()`` 默认情况下复用单例 AsyncClient，享受 httpx 内置连接池
   + HTTP/2 多路复用。每轮 14 源检索省 50-150ms × N 的 TLS 握手。
   传入 kwargs 时退化为「一次性 client」走原行为，不破坏现有 fetcher 子类。
2. ``safe_fetch`` 按异常类型分层重试：网络瞬态错（ConnectError/Timeout 等）
   指数退避；HTTP 4xx 立即放弃；HTTP 429/5xx 退避后重试。一锅烩 except 在
   永不会成功的请求上浪费 2-4 秒的浪费消除。

2026-05-03 付费 PDF 源抽象：
- ``PAID_PDF: bool`` 类属性把 "patenthub" 等付费源的特殊待遇下放到 fetcher 层，
  不再在 classification / fulltext_tasks / fulltext_service 里到处硬编码
  ``source == "patenthub"``。
- ``download_pdf_for_doc`` 让付费源用自己的鉴权 + 详情 + key 解析接口下载 PDF，
  不走 fulltext_service 的 httpx 多策略（那套是给免费源用的）。
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


# 网络瞬态错 —— 这些值得 retry（指数退避）
_RETRYABLE_NETWORK_ERRORS: Tuple[Type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    asyncio.TimeoutError,
)
_RETRYABLE_HTTP_STATUSES = frozenset({429, 502, 503, 504})


class AbstractFetcher(ABC):
    """所有数据源 fetcher 的基类"""

    DEFAULT_TIMEOUT = 20.0
    RETRY_COUNT = 2
    RETRY_DELAY = 1.0

    # 付费 PDF 源标志（2026-05-03）：True = 该源 PDF 下载收费，需要：
    #   1. 跳过 classify=very_relevant 的自动隐式触发，只响应用户手动点击；
    #   2. 不走 fulltext_service 的 httpx 多策略（那套设计给开放学术源），
    #      改调子类自己实现的 ``download_pdf_for_doc``（含 token 鉴权 / 详情接口
    #      / pdfList key 解析等）。
    # 配合 ``backend/app/services/fetchers/international.py`` 里的
    # ``is_paid_pdf_source`` / ``get_paid_pdf_source_ids`` 一起用。
    PAID_PDF: bool = False

    # 实例级缓存：每个 fetcher 一份默认 client，跨 fetch 调用复用。
    # _cached_client 不在类上而在实例上，子类天然不共享。
    _cached_client: Optional[httpx.AsyncClient] = None

    async def download_pdf_for_doc(self, doc: Dict, outfile: Path) -> bool:
        """付费 PDF 源专属：用源自己的 API 把 PDF 下到 ``outfile``，返回是否成功写盘。

        ``doc`` 至少包含 ``external_id`` / ``pdf_url`` / ``doi`` / ``title`` 等字段
        （由 fulltext_service 调用方填充），fetcher 自取所需。

        非付费源 (``PAID_PDF=False``) 不需要实现 — fulltext_service 会走 httpx
        多策略链，根本不会调到这里。
        """
        raise NotImplementedError(
            f"{self.source_id}.download_pdf_for_doc 未实现 "
            f"(PAID_PDF={self.PAID_PDF}) — 付费源应重写此方法；"
            f"免费源被调到此处说明上游路由跳过 PAID_PDF 检查了"
        )

    def _http_client(self, **kwargs) -> "_HttpClientContext":
        """获取 httpx.AsyncClient（async context manager 形式）。

        - 不传 kwargs：返回**共享**实例（连接池跨 fetch 调用复用），
          ``async with`` 退出时**不**关闭，全生命周期持有
        - 传 kwargs：返回一次性实例，``async with`` 退出时关闭（旧行为）
        """
        if kwargs:
            return _OneShotClientCM(self, kwargs)
        return _SharedClientCM(self)

    def _build_client(self, **kwargs) -> httpx.AsyncClient:
        from app.services.source_config_store import get_proxy_for_source

        if "timeout" not in kwargs:
            kwargs["timeout"] = self.DEFAULT_TIMEOUT
        # 启用 HTTP/2（OpenAlex/Crossref 等 CDN 后端受益）；h2 包未装则降级
        # 到 HTTP/1.1，避免生产 ImportError 阻断检索。
        if "http2" not in kwargs:
            try:
                import h2  # noqa: F401
                kwargs["http2"] = True
            except ImportError:
                kwargs["http2"] = False
        proxy = get_proxy_for_source(self.source_id)
        if proxy:
            kwargs["proxy"] = proxy
        return httpx.AsyncClient(**kwargs)

    async def aclose(self) -> None:
        """关闭共享 client（worker 退出时调用避免连接泄漏）。"""
        client = self._cached_client
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception as e:
                logger.warning("[%s] aclose error: %s", self.source_id, e)
        self._cached_client = None

    @property
    @abstractmethod
    def source_id(self) -> str:
        """数据源唯一标识（pubmed / openalex / arxiv / ...）"""
        pass

    @abstractmethod
    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        """实际抓取逻辑，由子类实现"""
        pass

    async def safe_fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> Tuple[str, List[Dict]]:
        """按异常类型分层的重试。

        - 网络瞬态错（ConnectError / Timeout 等）：指数退避重试 RETRY_COUNT 次
        - 整体 wait_for 超时：同上
        - HTTPStatusError 429/5xx：退避后重试
        - HTTPStatusError 4xx（除 429）：立即放弃，不浪费时间
        - 其他异常：当作 fetcher 内部 bug，立即放弃 + ERROR 日志
        """
        last_error = None
        for attempt in range(self.RETRY_COUNT + 1):
            try:
                data = await asyncio.wait_for(
                    self.fetch(query, max_results, year_from, year_to, language),
                    timeout=self.DEFAULT_TIMEOUT,
                )
                return (self.source_id, data or [])
            except _RETRYABLE_NETWORK_ERRORS as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "[%s] transient (attempt %d/%d): %s",
                    self.source_id, attempt + 1, self.RETRY_COUNT + 1, e,
                )
                if attempt < self.RETRY_COUNT:
                    await asyncio.sleep(self.RETRY_DELAY * (2 ** attempt))
                    continue
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in _RETRYABLE_HTTP_STATUSES:
                    last_error = f"HTTP {code}"
                    logger.warning(
                        "[%s] retryable HTTP %d (attempt %d/%d)",
                        self.source_id, code, attempt + 1, self.RETRY_COUNT + 1,
                    )
                    if attempt < self.RETRY_COUNT:
                        await asyncio.sleep(self.RETRY_DELAY * (2 ** attempt))
                        continue
                else:
                    logger.warning(
                        "[%s] non-retryable HTTP %d, giving up: %s",
                        self.source_id, code, e,
                    )
                    return (self.source_id, [])
            except Exception as e:
                logger.error(
                    "[%s] non-retryable exception, giving up: %s",
                    self.source_id, e,
                )
                return (self.source_id, [])

        logger.error("[%s] retries exhausted: %s", self.source_id, last_error)
        return (self.source_id, [])

    @staticmethod
    def now_iso() -> str:
        return datetime.now().isoformat()


# ── Context-manager helpers (kept inline so subclasses don't need to import) ──


class _HttpClientContext:
    """Common base — type tag for the two CM forms returned by _http_client."""

    async def __aenter__(self) -> httpx.AsyncClient:
        raise NotImplementedError

    async def __aexit__(self, *_: object) -> None:
        raise NotImplementedError


class _SharedClientCM(_HttpClientContext):
    """Default path — yields the fetcher's cached singleton client.
    ``async with`` exit is a no-op (the client outlives this scope).

    Loop affinity check (2026-05-03): Celery worker 的 `_run_async` 每个 task
    一个 new_event_loop + close。httpx.AsyncClient 的 transport 内部 socket /
    asyncio.Lock 都绑死在创建它的 loop 上 — 跨 task 复用 cached client 会
    在新 loop 里撞 `RuntimeError: Event loop is closed`。这里 enter 时把
    cached client 的 loop 跟当前 loop 比一下，不一致就当作"过期"丢弃重建
    （旧 client 不主动 aclose：原 loop 已关，aclose 也只能报错）。
    同 loop 内连续调用仍然复用，连接池收益保留。
    """

    def __init__(self, fetcher: AbstractFetcher) -> None:
        self._fetcher = fetcher

    async def __aenter__(self) -> httpx.AsyncClient:
        client = self._fetcher._cached_client
        current_loop = asyncio.get_running_loop()
        bound_loop = getattr(client, "_sp_loop", None) if client is not None else None
        stale_loop = client is not None and bound_loop is not current_loop
        if client is None or client.is_closed or stale_loop:
            client = self._fetcher._build_client()
            # 动态属性: 标记 client 绑定的 event loop, 跨 Celery task 检测 stale
            # mypy 看不到 httpx.AsyncClient 的动态字段, ignore attr-defined
            client._sp_loop = current_loop  # type: ignore[attr-defined]
            self._fetcher._cached_client = client
        return client

    async def __aexit__(self, *_: object) -> None:
        # No close — shared singleton lives across calls.
        return None


class _OneShotClientCM(_HttpClientContext):
    """Compatibility path — when the caller passes kwargs (custom headers,
    timeout, ...), build a fresh client and close it on exit. Preserves
    backwards-compatible semantics for fetchers that need request-specific
    client config."""

    def __init__(self, fetcher: AbstractFetcher, kwargs: dict) -> None:
        self._fetcher = fetcher
        self._kwargs = kwargs
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> httpx.AsyncClient:
        self._client = self._fetcher._build_client(**self._kwargs)
        return self._client

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass


class FetcherRegistry:
    """数据源注册表 — 扩展自 v1 的 EnhancedDataSourceRegistry"""

    SOURCES: Dict[str, Dict] = {
        "pubmed": {
            "name": "PubMed",
            "description": "美国国家医学图书馆生物医学文献数据库",
            "doc_type": "paper",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "openalex": {
            "name": "OpenAlex",
            "description": "完全开放的全领域学术数据库",
            "doc_type": "paper",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "semantic_scholar": {
            "name": "Semantic Scholar",
            "description": "AI 驱动的学术搜索引擎，提供引用分析",
            "doc_type": "paper",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "europe_pmc": {
            "name": "Europe PMC",
            "description": "欧洲生物医学文献数据库",
            "doc_type": "paper",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "arxiv": {
            "name": "arXiv",
            "description": "CS / 物理 / 数学 / 经济学预印本",
            "doc_type": "preprint",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "biorxiv": {
            "name": "bioRxiv",
            "description": "生物学预印本",
            "doc_type": "preprint",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "medrxiv": {
            "name": "medRxiv",
            "description": "医学预印本",
            "doc_type": "preprint",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "dblp": {
            "name": "DBLP",
            "description": "计算机科学顶级会议/期刊（CVPR/NeurIPS/ACL 等），免费 JSON API",
            "doc_type": "paper",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "openalex_zh": {
            "name": "OpenAlex (中文)",
            "description": "OpenAlex 中文论文专用：language:zh 过滤 + 原始中文查询词",
            "doc_type": "paper",
            "category": "literature",
            "language": "zh",
            "phase": 1,
        },
        "baidu_xueshu": {
            "name": "百度学术",
            "description": "暂不可用（百度 JS challenge 需要浏览器，httpx 无法绕过）",
            "doc_type": "paper",
            "category": "literature",
            "language": "zh",
            "phase": 2,
        },
        # Phase 2
        "wanfang": {
            "name": "万方数据",
            "description": "中文学术资源数据库",
            "doc_type": "paper",
            "category": "literature",
            "language": "zh",
            "phase": 2,
        },
        "baidu_scholar": {
            "name": "百度学术（旧占位）",
            "description": "已替换为 baidu_xueshu",
            "doc_type": "paper",
            "category": "literature",
            "language": "zh",
            "phase": 2,
        },
        "uspto": {
            "name": "USPTO (美国专利)",
            "description": "PatentsView API，美国专利全文检索",
            "doc_type": "patent",
            "category": "patents",
            "language": "en",
            "phase": 2,
        },
        "lens_patent": {
            "name": "Lens.org (全球专利)",
            "description": "覆盖 CN/US/EP/WO/JP/KR 等 90+ 国家专利，需配置 LENS_API_TOKEN",
            "doc_type": "patent",
            "category": "patents",
            "language": "multilingual",
            "phase": 1,
        },
        "epo_ops": {
            "name": "EPO OPS (欧洲专利局)",
            "description": "欧洲专利局官方 API，覆盖 EP/WO，需配置 EPO_CONSUMER_KEY/SECRET（免费）",
            "doc_type": "patent",
            "category": "patents",
            "language": "en",
            "phase": 1,
        },
        "cnipa": {
            "name": "CNIPA (中国专利)",
            "description": "中国国家知识产权局专利数据库",
            "doc_type": "patent",
            "category": "patents",
            "language": "zh",
            "phase": 2,
        },
        "patenthub": {
            "name": "PatentHub (中国专利)",
            "description": "专利汇 REST API，覆盖中国全部专利（发明/实用新型/外观设计），17万+ IPC 分类",
            "doc_type": "patent",
            "category": "patents",
            "language": "zh",
            "phase": 1,
        },
        "bigquery_patents": {
            "name": "Google Patents (中国专利)",
            "description": "Google BigQuery 公开专利数据集，~1500万条中国专利，中文标题+摘要",
            "doc_type": "patent",
            "category": "patents",
            "language": "zh",
            "phase": 1,
        },
        "clinical_trials": {
            "name": "ClinicalTrials.gov",
            "description": "美国临床试验注册数据库",
            "doc_type": "clinical_trial",
            "category": "clinical",
            "language": "en",
            "phase": 1,
        },
        "crossref": {
            "name": "Crossref",
            "description": "学术文献元数据聚合（1.3亿+记录）",
            "doc_type": "paper",
            "category": "literature",
            "language": "en",
            "phase": 1,
        },
        "local_kb": {
            "name": "Local Knowledge Base",
            "description": "本地 OpenAlex 知识库（BM25 + 引用图）",
            "doc_type": "paper",
            "category": "local",
            "language": "all",
            "phase": 3,
        },
    }

    @classmethod
    def get_phase1_sources(cls) -> List[str]:
        return [k for k, v in cls.SOURCES.items() if v["phase"] == 1]

    @classmethod
    def get_by_language(cls, language: str) -> List[str]:
        return [k for k, v in cls.SOURCES.items() if v.get("language") == language]

    @classmethod
    def get_all_info(cls) -> List[Dict]:
        return [{"id": k, **v} for k, v in cls.SOURCES.items()]
