"""
临床试验数据源 Fetcher
ClinicalTrials.gov API v2 — 免费，无需 API key
"""
import logging
from typing import Dict, List, Optional
import httpx
from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

CTGOV_BASE = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsFetcher(AbstractFetcher):
    source_id = "clinical_trials"
    DEFAULT_TIMEOUT = 20.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []
        params = {
            "query.term": query,
            "pageSize": min(max_results, 100),
            "sort": "@relevance",
            "fields": "NCTId,BriefTitle,OfficialTitle,BriefSummary,Condition,InterventionName,"
                      "OverallStatus,EnrollmentCount,StartDate,CompletionDate,LeadSponsorName,"
                      "Phase,StudyType",
            "format": "json",
        }

        # 年份过滤
        if year_from:
            params["query.term"] = f"{query} AREA[StartDate]RANGE[{year_from}-01-01, MAX]"

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            try:
                r = await client.get(CTGOV_BASE, params=params)
                if r.status_code == 200:
                    data = r.json()
                    for study in (data.get("studies") or []):
                        protocol = study.get("protocolSection", {})
                        id_module = protocol.get("identificationModule", {})
                        status_module = protocol.get("statusModule", {})
                        desc_module = protocol.get("descriptionModule", {})
                        design_module = protocol.get("designModule", {})
                        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
                        conditions_module = protocol.get("conditionsModule", {})
                        interventions_module = protocol.get("armsInterventionsModule", {})

                        nct_id = id_module.get("nctId", "")
                        title = id_module.get("officialTitle") or id_module.get("briefTitle", "")

                        # 构建摘要
                        summary_parts = []
                        brief = desc_module.get("briefSummary", "")
                        if brief:
                            summary_parts.append(brief)
                        conditions = conditions_module.get("conditions", [])
                        if conditions:
                            summary_parts.append(f"Conditions: {', '.join(conditions[:5])}")
                        interventions = interventions_module.get("interventions", [])
                        intervention_names = [i.get("name", "") for i in interventions[:5] if i.get("name")]
                        if intervention_names:
                            summary_parts.append(f"Interventions: {', '.join(intervention_names)}")
                        phase = (design_module.get("phases") or ["N/A"])
                        status = status_module.get("overallStatus", "")
                        if phase:
                            summary_parts.append(f"Phase: {', '.join(phase)}")
                        if status:
                            summary_parts.append(f"Status: {status}")

                        # 发起者作为 "authors"
                        sponsor = sponsor_module.get("leadSponsor", {}).get("name", "")

                        # 日期
                        start_date = status_module.get("startDateStruct", {}).get("date", "")

                        enrollment = design_module.get("enrollmentInfo", {}).get("count", 0)

                        papers.append({
                            "source": "clinical_trials",
                            "external_id": nct_id,
                            "doc_type": "clinical_trial",
                            "title": title,
                            "authors": sponsor,
                            "abstract": " | ".join(summary_parts),
                            "publication_date": start_date,
                            "journal": f"ClinicalTrials.gov ({', '.join(phase)})",
                            "doi": None,
                            "citation_count": enrollment or 0,  # 用入组人数作为影响力指标
                            "pdf_url": None,
                            "url": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else None,
                        })
                else:
                    logger.error("[ClinicalTrials] HTTP %d: %s", r.status_code, r.text[:200])
            except Exception as e:
                logger.error("[ClinicalTrials] %s: %s", type(e).__name__, e, exc_info=True)
        return papers[:max_results]
