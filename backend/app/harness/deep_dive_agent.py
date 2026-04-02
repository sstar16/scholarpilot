"""
Deep Dive Agent — 对单篇文献进行全文深度分析。
支持 PDF 下载 + 文本提取 + LLM 深度分析。
PDF 不可用时 fallback 到仅摘要分析。
"""
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

from app.harness.prompts.deep_dive import build_deep_dive_prompt

logger = logging.getLogger(__name__)


class DeepDiveAgent:
    """
    Downloads paper PDF, extracts text, and performs deep LLM analysis.
    """

    def __init__(self, llm_manager=None, pdf_storage_path: str = "./data/pdfs"):
        self._llm = llm_manager
        self._pdf_base = Path(pdf_storage_path)

    async def analyze(
        self,
        doc: Dict,
        project_description: str,
        user_memory: str = "",
        project_id: str = "",
    ) -> Optional[Dict]:
        """
        执行深度分析。

        Returns:
            分析结果 dict，或 None（完全失败时）
        """
        if not self._llm:
            logger.warning("[DeepDive] LLM 不可用")
            return None

        # Step 1: 尝试获取全文
        content = ""
        content_source = "abstract_only"

        # 优先使用已有的全文
        if doc.get("fulltext_text"):
            content = doc["fulltext_text"][:8000]
            content_source = "cached_fulltext"
        else:
            # 尝试下载 PDF
            pdf_path = await self._download_pdf(doc, project_id)
            if pdf_path:
                extracted = await self._extract_text(pdf_path)
                if extracted:
                    content = extracted[:8000]
                    content_source = "pdf_fulltext"

        # Fallback 到摘要
        if not content:
            abstract = doc.get("abstract") or doc.get("ai_summary") or ""
            if abstract:
                content = f"[仅摘要] {abstract}"
                content_source = "abstract_only"
            else:
                content = f"[仅标题] {doc.get('title', '')}"
                content_source = "title_only"

        # Step 2: LLM 深度分析
        prompt = build_deep_dive_prompt(
            project_description=project_description,
            doc=doc,
            content=content,
            user_memory=user_memory,
        )

        try:
            result = await self._llm.generate(prompt, temperature=0.2)
            if not result:
                logger.warning("[DeepDive] LLM 返回空结果")
                return None

            parsed = _parse_deep_dive_response(result)
            if not parsed:
                logger.warning("[DeepDive] 解析失败: %s", result[:200])
                return None

            parsed["content_source"] = content_source
            logger.info("[DeepDive] 分析完成: %s (%s)", doc.get("title", "")[:50], content_source)
            return parsed

        except Exception as e:
            logger.warning("[DeepDive] 分析异常: %s", e)
            return None

    async def _download_pdf(self, doc: Dict, project_id: str) -> Optional[str]:
        """尝试下载 PDF。返回本地路径或 None。"""
        pdf_url = doc.get("pdf_url")
        doi = doc.get("doi")

        # 如果没有直接 PDF URL，尝试通过 Unpaywall 查找开放获取版本
        if not pdf_url and doi:
            pdf_url = await self._unpaywall_lookup(doi)

        if not pdf_url:
            return None

        try:
            import httpx

            # 生成存储路径
            url_hash = hashlib.md5(pdf_url.encode()).hexdigest()[:12]
            proj_dir = self._pdf_base / (project_id or "default")
            proj_dir.mkdir(parents=True, exist_ok=True)
            local_path = proj_dir / f"{url_hash}.pdf"

            # 已下载过则直接返回
            if local_path.exists() and local_path.stat().st_size > 1000:
                return str(local_path)

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(pdf_url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    local_path.write_bytes(resp.content)
                    logger.info("[DeepDive] PDF 下载成功: %s (%d bytes)", local_path.name, len(resp.content))
                    return str(local_path)

        except Exception as e:
            logger.warning("[DeepDive] PDF 下载失败: %s", e)

        return None

    async def _unpaywall_lookup(self, doi: str) -> Optional[str]:
        """通过 Unpaywall API 查找开放获取 PDF。"""
        try:
            import httpx
            from app.config import settings
            email = settings.unpaywall_email
            url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    best = data.get("best_oa_location") or {}
                    pdf = best.get("url_for_pdf") or best.get("url")
                    if pdf:
                        return pdf
        except Exception as e:
            logger.debug("[DeepDive] Unpaywall 查询失败: %s", e)
        return None

    async def _extract_text(self, pdf_path: str) -> Optional[str]:
        """从 PDF 提取文本。"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            text_parts = []
            for page in doc:
                text_parts.append(page.get_text())
                if len("\n".join(text_parts)) > 10000:
                    break
            doc.close()
            text = "\n".join(text_parts).strip()
            return text if len(text) > 100 else None
        except ImportError:
            logger.debug("[DeepDive] PyMuPDF 未安装，尝试 pdfplumber")

        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages[:20]:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
                    if len("\n".join(text_parts)) > 10000:
                        break
            text = "\n".join(text_parts).strip()
            return text if len(text) > 100 else None
        except ImportError:
            logger.warning("[DeepDive] 无 PDF 解析库可用（需安装 PyMuPDF 或 pdfplumber）")

        return None


def _parse_deep_dive_response(text: str) -> Optional[Dict]:
    """解析 LLM 深度分析的 JSON 输出。"""
    match = re.search(r'\{[\s\S]*"detailed_analysis"[\s\S]*\}', text)
    if not match:
        match = re.search(r'\{[\s\S]+\}', text)
        if not match:
            return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    if "detailed_analysis" not in data:
        return None

    return {
        "detailed_analysis": str(data.get("detailed_analysis", ""))[:2000],
        "methodology": str(data.get("methodology", ""))[:500],
        "key_findings": data.get("key_findings", [])[:10],
        "limitations": data.get("limitations", [])[:5],
        "relevance_to_project": str(data.get("relevance_to_project", ""))[:500],
        "updated_one_liner": str(data.get("updated_one_liner", ""))[:100],
        "recommended_followup": data.get("recommended_followup", [])[:5],
    }
