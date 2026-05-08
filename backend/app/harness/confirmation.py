"""
Universal Confirmation Protocol — 通用确认协议。

所有 Agent 决策点统一使用此协议：
- 确认 (confirm) — 接受 Agent 方案（可附带 inline edits）
- 补充 (supplement) — 追加自然语言上下文，Agent 重新分析
- 取消 (cancel) — 回退到上一状态
- 自动确认 (auto_confirm) — 设置 flag，后续同类决策自动跳过
"""
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ConfirmationEnvelope:
    """通用确认信封 — 包装任何需要用户确认的 Agent 决策。"""
    confirmation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""             # "intent_analysis", "query_plan", "search_mode"
    action_type: str = ""            # 决策类型标识
    summary_zh: str = ""             # 中文摘要（展示给用户）
    details: dict = field(default_factory=dict)    # 完整结构化数据（可编辑字段）
    options: list = field(default_factory=lambda: ["confirm", "supplement", "cancel", "auto_confirm"])
    auto_confirmable: bool = True    # 是否提供自动确认选项
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConfirmationEnvelope":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# 中文标签映射 — 跟前端 ConfirmationBubble 共享同一份枚举语义。
# 后端在 summary 里直接用中文，避免 LLM 自由生成时把 "both" 写成 "buth" 之类的拼写错误。
_DOMAIN_LABELS = {
    "biology": "生物学",
    "chemistry": "化学",
    "physics": "物理学",
    "medicine": "医学",
    "engineering": "工程",
    "computer_science": "计算机科学",
    "mathematics": "数学",
    "materials_science": "材料科学",
    "environmental_science": "环境科学",
    "agriculture": "农业",
    "psychology": "心理学",
    "economics": "经济学",
    "social_science": "社会科学",
    "law": "法学",
    "interdisciplinary": "跨学科",
}
_DOC_TYPE_LABELS = {
    "literature": "学术文献",
    "patent": "专利",
    "both": "文献 + 专利",
}
_SCOPE_LABELS = {
    "chinese_first": "中文优先",
    "international": "国际英文",
    "global": "全球多语言",
}
_YEAR_FOCUS_LABELS = {
    "recent": "近 5 年",
    "decade": "近 10 年",
    "all": "全时间",
}


def _zh(label_map: dict, value, fallback: str = "未指定") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return "、".join(label_map.get(v, v) for v in value) or fallback
    return label_map.get(value, str(value))


def build_intent_envelope(intent_result: dict) -> ConfirmationEnvelope:
    """从 IntentAnalysisAgent 输出构建确认信封。

    summary_zh 由 details 字段反向格式化生成（带中文标签），保证显示与可编辑字段
    始终一致 —— 杜绝 LLM 自由生成 summary 与 details 不同步的情况。
    """
    title = intent_result.get("title", "未知项目")
    description = intent_result.get("description", "")
    confidence = intent_result.get("confidence", 0)

    domains_zh = _zh(_DOMAIN_LABELS, intent_result.get("domains"), "未分类")
    doc_types_zh = _zh(_DOC_TYPE_LABELS, intent_result.get("doc_types"), "学术文献")
    scope_zh = _zh(_SCOPE_LABELS, intent_result.get("scope"), "国际英文")
    year_focus_zh = _zh(_YEAR_FOCUS_LABELS, intent_result.get("year_focus"), "近 5 年")

    summary_parts = [f"**项目标题**: {title}"]
    if description and description != title:
        summary_parts.append(f"**研究描述**: {description}")
    summary_parts.append(f"**研究领域**: {domains_zh}")
    summary_parts.append(f"**文献类型**: {doc_types_zh}")
    summary_parts.append(f"**检索范围**: {scope_zh}")
    summary_parts.append(f"**时间窗口**: {year_focus_zh}")
    if intent_result.get("key_concepts"):
        summary_parts.append(f"**关键概念**: {'、'.join(intent_result['key_concepts'][:8])}")

    clarification = intent_result.get("clarification_needed")
    if clarification:
        summary_parts.append(f"\n> Agent 需要澄清：{clarification}")

    # 把中文 label 也回填进 details，让前端可编辑面板和摘要字段一致
    details = dict(intent_result)
    details["_labels"] = {
        "domains": domains_zh,
        "doc_types": doc_types_zh,
        "scope": scope_zh,
        "year_focus": year_focus_zh,
    }

    return ConfirmationEnvelope(
        agent_name="intent_analysis",
        action_type="project_intent",
        summary_zh="\n".join(summary_parts),
        details=details,
        auto_confirmable=confidence >= 0.6,
    )


def build_search_mode_envelope() -> ConfirmationEnvelope:
    """构建检索模式选择信封。"""
    return ConfirmationEnvelope(
        agent_name="system",
        action_type="search_mode",
        summary_zh="请选择检索模式：\n- **静态库** — 从本地知识库推荐（快速，<1s）\n- **API** — 实时搜索最新数据（较慢，需网络）\n- **混合** — 两者结合（推荐）",
        details={"modes": ["static_db", "api", "hybrid"]},
        options=["static_db", "api", "hybrid"],
        auto_confirmable=False,
    )


def check_auto_confirm(state_data: dict, action_type: str) -> bool:
    """检查某个 action_type 是否已设置自动确认。"""
    auto_flags = state_data.get("auto_confirm", {})
    return auto_flags.get(action_type, False)


def set_auto_confirm(state_data: dict, action_type: str) -> dict:
    """设置某个 action_type 的自动确认 flag。"""
    if "auto_confirm" not in state_data:
        state_data["auto_confirm"] = {}
    state_data["auto_confirm"][action_type] = True
    return state_data
