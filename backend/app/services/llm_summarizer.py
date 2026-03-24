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

严格按照以下JSON格式输出，不要有其他内容：
{{"summary": "...", "key_points": ["...", "...", "..."], "relevance_reason": "..."}}"""

SIGNAL_PROMPT = """用户对一篇科研文献给出了反馈。请从反馈原因中提取结构化信号。

反馈相关度：{relevance_label}
反馈原因：{reason}

请提取：
- positive_signals：支持相关性的特征（适用于正向反馈）
- negative_signals：不相关的原因（适用于负向反馈）

输出JSON：{{"positive_signals": ["..."], "negative_signals": ["..."]}}"""

RELEVANCE_LABELS = {-1: "完全无关", 0: "不确定", 1: "相关", 2: "非常相关"}


class LLMSummarizer:
    def __init__(self, llm_manager: LLMProviderManager):
        self._llm = llm_manager

    async def generate_summary(
        self,
        doc: Dict,
        project_description: str,
        use_fulltext: bool = False,
    ) -> Tuple[Optional[str], Optional[list], Optional[str], str]:
        """
        生成 AI 摘要
        返回: (summary, key_points, relevance_reason, summary_source)
        summary_source: 'from_abstract' | 'from_fulltext'
        """
        title = doc.get("title", "")
        fulltext = doc.get("fulltext_text") if use_fulltext else None
        abstract = doc.get("abstract", "")

        if fulltext and len(fulltext) > 200:
            content = fulltext[:8000]  # LLM context 限制
            content_label = "全文节选"
            summary_source = "from_fulltext"
        elif abstract and len(abstract) > 50:
            content = abstract[:3000]
            content_label = "摘要"
            summary_source = "from_abstract"
        else:
            # 无内容可用，直接返回 None
            return None, None, None, "not_generated"

        prompt = SUMMARY_PROMPT.format(
            project_description=project_description[:500],
            title=title,
            content_label=content_label,
            content=content,
        )

        raw = await self._llm.generate(prompt, temperature=0.3)
        if not raw:
            return None, None, None, "not_generated"

        try:
            # 尝试从输出中提取 JSON
            json_str = self._extract_json(raw)
            data = json.loads(json_str)
            return (
                data.get("summary"),
                data.get("key_points", []),
                data.get("relevance_reason"),
                summary_source,
            )
        except Exception as e:
            print(f"[Summarizer] JSON 解析失败: {e}\nRaw: {raw[:200]}")
            # 降级：将整个输出作为摘要
            return raw[:500], [], None, summary_source

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
        # 先尝试直接解析
        text = text.strip()
        if text.startswith("{"):
            return text
        # 查找 {} 包裹的部分
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return match.group(0)
        return text
