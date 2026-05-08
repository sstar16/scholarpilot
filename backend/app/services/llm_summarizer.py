"""
LLM 摘要生成服务
从文章全文（或 abstract）生成 AI 中文摘要、关键要点、与项目的关联说明
"""
import json
import re
from typing import Dict, Optional, Tuple
from app.services.core.llm_providers import LLMProviderManager

SUMMARY_PROMPT = """你是一位专业的科研助手，擅长阅读和分析各领域文献。

项目背景：
{project_description}

文献内容（标题 + 摘要/全文节选）：
标题：{title}
{content_label}：
{content}

请完成以下任务：
1. 用自己的语言写一段200-300字的中文摘要（不要照搬原文，要归纳核心发现和意义）
2. 列出3-5条关键要点（每条不超过30字）
3. 用1句话说明这篇文献与以上项目的关联性
4. 结构化抽取：核心概念、方法、主要结果、引文

严格按照以下JSON格式输出，不要有其他内容：
{{
  "summary": "...",
  "key_points": ["...", "...", "..."],
  "relevance_reason": "...",
  "concepts": [
    {{"name": "概念名", "type": "method|theory|dataset|metric|task", "confidence": 0.0}}
  ],
  "methods": [
    {{"name": "方法名", "short": "20字内中文描述"}}
  ],
  "results": [
    {{"claim": "40字内结论", "evidence": "20字内来源如Table2/§4.1"}}
  ],
  "citations_mentioned": ["Author et al. Year", "..."]
}}

约束:
- concepts / methods / results / citations_mentioned 四个数组必须存在(即使为空 [])
- concept.confidence 必须在 0.0-1.0 之间
- 不要编造不在原文的引文或结果
- 如果无法抽取某个字段,返回空数组而不是省略该字段"""

SIGNAL_PROMPT = """用户对一篇科研文献给出了反馈。请从反馈原因中提取结构化信号。

反馈相关度：{relevance_label}
反馈原因：{reason}

请提取：
- positive_signals：支持相关性的特征（适用于正向反馈）
- negative_signals：不相关的原因（适用于负向反馈）

输出JSON：{{"positive_signals": ["..."], "negative_signals": ["..."]}}"""

EXTRACT_ONLY_PROMPT = """你是一位专业的科研助手，擅长分析各领域文献。以下文献已有中文摘要（用户会直接阅读原文），请只做结构化抽取，不要重写摘要。

项目背景：
{project_description}

标题：{title}
原文中文摘要：
{abstract}

请完成：
1. 列出 3-5 条关键要点（每条不超过 30 字）
2. 用 1 句话说明这篇文献与以上项目的关联性
3. 结构化抽取：核心概念、方法、主要结果、引文

严格按照以下 JSON 格式输出，不要有其他内容：
{{
  "key_points": ["...", "...", "..."],
  "relevance_reason": "...",
  "concepts": [
    {{"name": "概念名", "type": "method|theory|dataset|metric|task", "confidence": 0.0}}
  ],
  "methods": [
    {{"name": "方法名", "short": "20字内中文描述"}}
  ],
  "results": [
    {{"claim": "40字内结论", "evidence": "20字内来源如Table2/§4.1"}}
  ],
  "citations_mentioned": ["Author et al. Year", "..."]
}}

约束:
- concepts / methods / results / citations_mentioned 四个数组必须存在(即使为空 [])
- concept.confidence 必须在 0.0-1.0 之间
- 不要编造不在原文的引文或结果
- 如果无法抽取某个字段,返回空数组而不是省略该字段"""

RELEVANCE_LABELS = {-1: "完全无关", 0: "不确定", 1: "相关", 2: "非常相关"}


_CJK_RE = re.compile(r"[一-鿿]")


def _is_cjk_text(text: str, threshold: float = 0.3) -> bool:
    """判断文本是否主要为中文（中文字符占比 ≥ threshold）。"""
    if not text or len(text) < 20:
        return False
    return len(_CJK_RE.findall(text)) / len(text) >= threshold


_PLACEHOLDER_KEYWORDS = {
    "示例", "待补充", "example", "placeholder", "todo", "tbd",
    "未提供", "not provided", "n/a", "na", "-", "?",
}
_MAX_CONCEPTS = 20
_MAX_METHODS = 20
_MAX_RESULTS = 20
_MAX_CITATIONS = 30
_MAX_NAME_LEN = 60
_MAX_SHORT_LEN = 50
_MAX_CLAIM_LEN = 80
_MAX_EVIDENCE_LEN = 40
_MIN_CONFIDENCE = 0.3


def _is_placeholder(text: str) -> bool:
    if not text:
        return True
    lower = str(text).strip().lower()
    if not lower:
        return True
    return lower in _PLACEHOLDER_KEYWORDS


def sanitize_extraction(raw: dict) -> dict:
    """
    Apply defensive filtering on LLM extraction fields.

    三层兜底: 字段校验 + 占位符剔除 + 低置信度过滤.
    对应 memory: feedback_llm_parser_fallback.
    Sets `_extract_status` to "ok" / "partial" / "failed".
    """
    status = "ok"
    extracted: dict = {}

    # --- concepts ---
    concepts_raw = raw.get("concepts") or []
    concepts: list[dict] = []
    if isinstance(concepts_raw, list):
        for c in concepts_raw[:_MAX_CONCEPTS]:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", "")).strip()[:_MAX_NAME_LEN]
            if _is_placeholder(name):
                continue
            ctype = str(c.get("type", "")).strip()[:20] or "concept"
            try:
                conf = float(c.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            conf = max(0.0, min(1.0, conf))
            if conf < _MIN_CONFIDENCE:
                continue
            concepts.append({"name": name, "type": ctype, "confidence": round(conf, 3)})
    else:
        status = "partial"
    extracted["concepts"] = concepts

    # --- methods ---
    methods_raw = raw.get("methods") or []
    methods: list[dict] = []
    if isinstance(methods_raw, list):
        for m in methods_raw[:_MAX_METHODS]:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name", "")).strip()[:_MAX_NAME_LEN]
            if _is_placeholder(name):
                continue
            short = str(m.get("short", "")).strip()[:_MAX_SHORT_LEN]
            methods.append({"name": name, "short": short})
    else:
        status = "partial"
    extracted["methods"] = methods

    # --- results ---
    results_raw = raw.get("results") or []
    results: list[dict] = []
    if isinstance(results_raw, list):
        for r in results_raw[:_MAX_RESULTS]:
            if not isinstance(r, dict):
                continue
            claim = str(r.get("claim", "")).strip()[:_MAX_CLAIM_LEN]
            if _is_placeholder(claim):
                continue
            evidence = str(r.get("evidence", "")).strip()[:_MAX_EVIDENCE_LEN]
            results.append({"claim": claim, "evidence": evidence})
    else:
        status = "partial"
    extracted["results"] = results

    # --- citations ---
    cit_raw = raw.get("citations_mentioned") or []
    citations: list[str] = []
    if isinstance(cit_raw, list):
        for c in cit_raw[:_MAX_CITATIONS]:
            if not isinstance(c, str):
                continue
            s = c.strip()[:100]
            if _is_placeholder(s):
                continue
            citations.append(s)
    else:
        status = "partial"
    extracted["citations_mentioned"] = citations

    # Missing all four → failed
    if not any([concepts, methods, results, citations]):
        status = "failed" if status == "ok" else status

    extracted["_extract_status"] = status
    return extracted


class LLMSummarizer:
    def __init__(self, llm_manager: LLMProviderManager):
        self._llm = llm_manager

    async def generate_summary(
        self,
        doc: Dict,
        project_description: str,
        use_fulltext: bool = False,
    ) -> Dict:
        """
        生成 AI 摘要 + 结构化抽取。
        返回 dict:
            {
                "summary": str | None,
                "key_points": list[str],
                "relevance_reason": str | None,
                "summary_source": "from_abstract"|"from_fulltext"|"from_title"|"not_generated",
                "concepts": list[dict],
                "methods": list[dict],
                "results": list[dict],
                "citations_mentioned": list[str],
                "_extract_status": "ok"|"partial"|"failed"|"not_generated",
            }
        """
        title = doc.get("title", "")
        fulltext = doc.get("fulltext_text") if use_fulltext else None
        abstract = doc.get("abstract", "")

        empty = {
            "summary": None,
            "key_points": [],
            "relevance_reason": None,
            "summary_source": "not_generated",
            "concepts": [],
            "methods": [],
            "results": [],
            "citations_mentioned": [],
            "_extract_status": "not_generated",
        }

        # 原文 abstract 已是中文：summary 直接用原文（不让 LLM 重写），
        # 但仍走一次轻量 LLM 调用做结构化抽取（key_points / relevance / concepts / methods / results / citations）
        if abstract and len(abstract) > 50 and _is_cjk_text(abstract):
            extract_prompt = EXTRACT_ONLY_PROMPT.format(
                project_description=project_description[:500],
                title=title,
                abstract=abstract[:3000],
            )
            raw = await self._llm.generate(extract_prompt, temperature=0.3)
            result = {
                "summary": abstract.strip(),
                "key_points": [],
                "relevance_reason": None,
                "summary_source": "from_abstract",
                "concepts": [],
                "methods": [],
                "results": [],
                "citations_mentioned": [],
                "_extract_status": "not_generated",
            }
            if raw:
                try:
                    data = json.loads(self._extract_json(raw))
                    sanitized = sanitize_extraction(data)
                    result.update({
                        "key_points": data.get("key_points", []),
                        "relevance_reason": data.get("relevance_reason"),
                        "concepts": sanitized["concepts"],
                        "methods": sanitized["methods"],
                        "results": sanitized["results"],
                        "citations_mentioned": sanitized["citations_mentioned"],
                        "_extract_status": sanitized["_extract_status"],
                    })
                except Exception as e:
                    print(f"[Summarizer] 中文 abstract 抽取 JSON 解析失败: {e}\nRaw: {raw[:200]}")
                    result["_extract_status"] = "failed"
            return result

        if fulltext and len(fulltext) > 200:
            content = fulltext[:8000]
            content_label = "全文节选"
            summary_source = "from_fulltext"
        elif abstract and len(abstract) > 50:
            content = abstract[:3000]
            content_label = "摘要"
            summary_source = "from_abstract"
        elif title and len(title) > 3:
            content = title
            content_label = "标题"
            summary_source = "from_title"
        else:
            return empty

        prompt = SUMMARY_PROMPT.format(
            project_description=project_description[:500],
            title=title,
            content_label=content_label,
            content=content,
        )

        raw = await self._llm.generate(prompt, temperature=0.3)
        if not raw:
            print(f"[Summarizer] LLM 返回空，title={title[:60]}, source={summary_source}")
            result = dict(empty)
            result["summary_source"] = summary_source
            return result

        try:
            json_str = self._extract_json(raw)
            data = json.loads(json_str)
        except Exception as e:
            print(f"[Summarizer] JSON 解析失败: {e}\nRaw: {raw[:200]}")
            return {
                "summary": raw[:500],
                "key_points": [],
                "relevance_reason": None,
                "summary_source": summary_source,
                "concepts": [],
                "methods": [],
                "results": [],
                "citations_mentioned": [],
                "_extract_status": "failed",
            }

        # 成功解析 - 合并 sanitize 后的结构化抽取字段
        sanitized = sanitize_extraction(data)

        return {
            "summary": data.get("summary"),
            "key_points": data.get("key_points", []),
            "relevance_reason": data.get("relevance_reason"),
            "summary_source": summary_source,
            "concepts": sanitized["concepts"],
            "methods": sanitized["methods"],
            "results": sanitized["results"],
            "citations_mentioned": sanitized["citations_mentioned"],
            "_extract_status": sanitized["_extract_status"],
        }

    async def extract_feedback_signals(
        self,
        reason: str,
        relevance: int,
    ) -> Tuple[list, list]:
        """从反馈原因提取正负信号"""
        if not reason or len(reason.strip()) < 5:
            return [], []

        prompt = SIGNAL_PROMPT.format(
            relevance_label=RELEVANCE_LABELS.get(relevance, "未知"),
            reason=reason[:500],
        )
        raw = await self._llm.generate(prompt, temperature=0.1)
        if not raw:
            return [], []
        try:
            data = json.loads(self._extract_json(raw))
            return data.get("positive_signals", []), data.get("negative_signals", [])
        except Exception:
            return [], []

    @staticmethod
    def _extract_json(text: str) -> str:
        """从 LLM 输出中提取 JSON 字符串"""
        text = text.strip()
        # 去除 markdown 代码块包裹: ```json ... ``` 或 ``` ... ```
        code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if code_block:
            return code_block.group(1)
        if text.startswith("{"):
            return text
        # 查找 {} 包裹的部分
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return match.group(0)
        return text
