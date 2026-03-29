"""
AbstractFetcher 基类
继承自 v1 的 _safe_fetch + asyncio.gather 模式
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime


class AbstractFetcher(ABC):
    """所有数据源 fetcher 的基类"""

    DEFAULT_TIMEOUT = 20.0
    RETRY_COUNT = 2
    RETRY_DELAY = 1.0

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
        """带超时和重试的安全执行封装（继承自 v1 的 _safe_fetch 模式）"""
        last_error = None
        for attempt in range(self.RETRY_COUNT + 1):
            try:
                data = await asyncio.wait_for(
                    self.fetch(query, max_results, year_from, year_to, language),
                    timeout=self.DEFAULT_TIMEOUT,
                )
                return (self.source_id, data or [])
            except asyncio.TimeoutError:
                last_error = f"请求超时({self.DEFAULT_TIMEOUT}s)"
                if attempt < self.RETRY_COUNT:
                    await asyncio.sleep(self.RETRY_DELAY)
            except Exception as e:
                last_error = str(e)
                print(f"[{self.source_id}] 第{attempt+1}次失败: {e}")
                if attempt < self.RETRY_COUNT:
                    await asyncio.sleep(self.RETRY_DELAY)

        print(f"[{self.source_id}] 所有重试失败: {last_error}")
        return (self.source_id, [])

    @staticmethod
    def now_iso() -> str:
        return datetime.now().isoformat()


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
            "name": "百度学术",
            "description": "百度学术中文文献检索",
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
        "cnipa": {
            "name": "CNIPA (中国专利)",
            "description": "中国国家知识产权局专利数据库",
            "doc_type": "patent",
            "category": "patents",
            "language": "zh",
            "phase": 2,
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
