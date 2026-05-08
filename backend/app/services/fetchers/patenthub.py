"""
PatentHub (专利汇) Fetcher
REST API，API Token 认证，覆盖中国全部专利（发明/实用新型/外观设计）+ 全球部分专利。

三段式接口（计费单位，2026-04-24 工作人员确认）：
- /api/s          搜索    0.1 元/次，1 页 = 1 次，ps 最大 50
- /api/patent/base 详情   0.1 元/次（与搜索共享计费），参数 `id`（不是 uniqueId），返回含 pdfList
- /api/pdf        PDF下载 1 元/次，参数 `key` 必须来自 pdfList，不能用专利号
- 实际每篇 PDF 成本 = 1 次详情 + 1 次 PDF = ¥1.1（必须先调详情拿 key）

注册：https://www.patenthub.cn
配置：
- .env / docker-compose env:  PATENTHUB_API_TOKEN=xxx        （兜底）
- DevTools Sources UI:        patenthub → PATENTHUB_API_TOKEN  （运行时，优先级更高）
两者共存 → DevTools 胜出（见 _get_token）
"""
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

PATENTHUB_BASE = "https://www.patenthub.cn"
PATENTHUB_SEARCH_URL = f"{PATENTHUB_BASE}/api/s"
PATENTHUB_DETAIL_URL = f"{PATENTHUB_BASE}/api/patent/base"
PATENTHUB_PDF_URL = f"{PATENTHUB_BASE}/api/pdf"


class PatentHubFetcher(AbstractFetcher):
    """PatentHub 中国 + 部分国际专利检索 / 详情 / PDF 下载"""

    source_id = "patenthub"
    PAID_PDF = True  # 详情 ¥0.1 + PDF ¥1 = ¥1.1/篇，不进自动批量；走 download_pdf_for_doc
    DEFAULT_TIMEOUT = 25.0
    PDF_DOWNLOAD_TIMEOUT = 60.0

    def __init__(self):
        self._token = os.getenv("PATENTHUB_API_TOKEN", "")

    async def download_pdf_for_doc(self, doc: Dict, outfile: Path) -> bool:
        """付费源接口：从 doc 里取 patent number → download_pdf_by_patent。

        约定 ``external_id`` = patent documentNumber（搜索接口里就是这个，
        见 _parse_patent line 108）。``patent_number`` 是历史别名，向后兼容。
        """
        patent_id = doc.get("external_id") or doc.get("patent_number")
        if not patent_id:
            logger.warning("[PatentHub] download_pdf_for_doc: doc 缺 external_id/patent_number")
            return False
        return await self.download_pdf_by_patent(patent_id, outfile)

    async def _get_token(self) -> str:
        """获取 token：DevTools 凭证覆盖 > 环境变量"""
        from app.services.source_config_store import get_credential
        token = await get_credential("patenthub", "PATENTHUB_API_TOKEN")
        return token or self._token

    # ─────────────────────────────── 搜索接口 ───────────────────────────────
    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        token = await self._get_token()
        if not token:
            logger.warning("[PatentHub] PATENTHUB_API_TOKEN 未配置，跳过")
            return []

        q = query.strip()
        if not q:
            return []

        if year_from or year_to:
            yf = f"{year_from}0101" if year_from else "19850101"
            yt = f"{year_to}1231" if year_to else "20991231"
            q = f"({q}) AND ad=[{yf} TO {yt}]"

        count = min(max_results, 50)
        params = {
            "t": token,
            "q": q,
            "ds": "cn",
            "p": "1",
            "ps": str(count),
            "v": "1",
        }

        async with self._http_client() as client:
            try:
                r = await client.get(PATENTHUB_SEARCH_URL, params=params)
                if r.status_code != 200:
                    logger.warning("[PatentHub] 搜索 HTTP %d: %s", r.status_code, r.text[:200])
                    return []

                data = r.json()
                if not data.get("success"):
                    code = data.get("code", "?")
                    logger.warning("[PatentHub] 搜索 API 错误 code=%s: %s", code, data.get("message", ""))
                    return []

                total = data.get("total", 0)
                patents = data.get("patents", [])
                logger.info("[PatentHub] 搜索 '%s' → %d 条 (总 %d)", query[:30], len(patents), total)

                return [self._parse_patent(p) for p in patents]

            except Exception as e:
                logger.error("[PatentHub] fetch 异常: %s", e, exc_info=True)
                return []

    def _parse_patent(self, p: dict) -> Dict:
        """搜索接口响应 → 统一 doc schema。字段映射参考 2026-04-24 实测。"""
        doc_number = p.get("documentNumber", "") or p.get("id", "")
        app_number = p.get("applicationNumber", "")
        title = p.get("title", "") or doc_number

        inventor = p.get("inventor", "")
        applicant = p.get("applicant", "")
        authors = inventor or applicant

        pub_date = p.get("documentDate") or p.get("applicationDate")

        ipc = p.get("mainIpc", "") or p.get("ipc", "")
        cpc = p.get("cpc", "")

        legal_status = p.get("legalStatus", "")
        current_status = p.get("currentStatus", "")
        patent_type = p.get("type", "")

        legal_event = p.get("legalEvent", []) or []
        if isinstance(legal_event, list):
            legal_event_str = " / ".join(str(e) for e in legal_event)
        else:
            legal_event_str = str(legal_event)

        url = f"{PATENTHUB_BASE}/patent/{doc_number}.html" if doc_number else None

        legal_combined = (
            f"{legal_status} / {current_status}" if legal_status and current_status
            else (legal_status or current_status)
        )

        return {
            "source": "patenthub",
            "external_id": doc_number,
            "doc_type": "patent",
            "title": title,
            "authors": authors,
            "abstract": p.get("summary", ""),
            "publication_date": pub_date,
            "journal": f"CN Patent ({patent_type})" if patent_type else "CN Patent",
            "doi": None,
            "citation_count": 0,
            "pdf_url": None,  # 搜索不返 pdfList，需 get_detail 才有
            "url": url,
            "patent_number": doc_number,
            "application_number": app_number,
            "applicant": applicant,
            "applicant_type": p.get("applicantType", ""),
            "current_assignee": p.get("currentAssignee", ""),
            "ipc": ipc,
            "cpc": cpc,
            "legal_status": legal_combined,
            "legal_event": legal_event_str,
            "family_id": p.get("familyId", ""),
            "extended_family_id": p.get("extendedFamilyId", ""),
        }

    # ─────────────────────────────── 详情接口 ───────────────────────────────
    async def get_detail(self, patent_id: str) -> Optional[Dict]:
        """
        调 /api/patent/base 拿完整详情 + pdfList。
        返回整个 `patent` 对象（含 pdfList），失败返回 None。
        参数名必须是 `id`（文档写的 uniqueId 是错的，2026-04-24 实测）。
        """
        token = await self._get_token()
        if not token or not patent_id:
            return None

        params = {"t": token, "v": "1", "id": patent_id}

        async with self._http_client() as client:
            try:
                r = await client.get(PATENTHUB_DETAIL_URL, params=params)
                if r.status_code != 200:
                    logger.warning("[PatentHub] 详情 HTTP %d id=%s: %s",
                                   r.status_code, patent_id, r.text[:200])
                    return None
                data = r.json()
                if not data.get("success"):
                    logger.warning("[PatentHub] 详情失败 code=%s id=%s",
                                   data.get("code"), patent_id)
                    return None
                return data.get("patent") or {}
            except Exception as e:
                logger.error("[PatentHub] get_detail 异常 id=%s: %s", patent_id, e, exc_info=True)
                return None

    # ─────────────────────────────── PDF 下载 ───────────────────────────────
    async def download_pdf_file(self, pdf_key: str, outfile: Path) -> bool:
        """
        调 /api/pdf 下载 PDF 到本地。pdf_key 必须来自 get_detail 的 pdfList。
        成功返回 True（已写盘），失败返回 False（不写盘）。
        **每次成功调用计 1 元**，调用方负责预算守门。
        """
        token = await self._get_token()
        if not token or not pdf_key:
            return False

        params = {"t": token, "v": "1", "key": pdf_key}

        async with self._http_client(timeout=self.PDF_DOWNLOAD_TIMEOUT) as client:
            try:
                r = await client.get(PATENTHUB_PDF_URL, params=params)
                if r.status_code != 200:
                    logger.warning("[PatentHub] PDF HTTP %d key=%s", r.status_code, pdf_key[:60])
                    return False
                body = r.content
                if not body or body[:5] != b"%PDF-":
                    logger.warning("[PatentHub] 返回非 PDF 内容 key=%s size=%d",
                                   pdf_key[:60], len(body))
                    return False

                outfile.parent.mkdir(parents=True, exist_ok=True)
                outfile.write_bytes(body)
                logger.info("[PatentHub] PDF 下载成功 %s (%d bytes)", outfile.name, len(body))
                return True
            except Exception as e:
                logger.error("[PatentHub] download_pdf_file 异常 key=%s: %s",
                             pdf_key[:60], e, exc_info=True)
                return False

    async def download_pdf_by_patent(self, patent_id: str, outfile: Path) -> bool:
        """
        一站式：详情 → pdfList[0] → /api/pdf 下载到 outfile。
        计费：1 次详情（0.1 元） + 1 次 PDF（1 元）= 每篇 ¥1.1（2026-04-24 确认）。
        """
        detail = await self.get_detail(patent_id)
        if not detail:
            return False
        pdf_list = detail.get("pdfList") or []
        if not pdf_list:
            logger.info("[PatentHub] 专利 %s 无 PDF（海外专利常见）", patent_id)
            return False
        return await self.download_pdf_file(pdf_list[0], outfile)
