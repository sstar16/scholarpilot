"""
IntentAnalysis Agent prompt —— 从 md 模板构建。
模板: backend/app/prompts/agents/intent_analysis.md
改 md 不需要重启 worker（mtime 热重载）。
"""
from app.services.prompt_loader import load_prompt


def build_intent_prompt(
    user_input: str,
    supplementary_context: str = "",
) -> tuple[str, str]:
    """
    构建 IntentAnalysisAgent prompt。

    Returns:
        (combined_prompt, "") — 为兼容原 (system, user) 元组签名，
        新版 md 里已经合并 system+user template，combined 即完整 prompt。
        调用方继续用 f"{system}\\n\\n---\\n\\n{user}" 拼接，末尾多一个分隔符不影响 LLM。
    """
    supplement_section = ""
    if supplementary_context:
        supplement_section = f"## 用户补充说明\n{supplementary_context}"

    pf = load_prompt("agents/intent_analysis")
    rendered = pf.render(
        user_input=user_input[:1000],
        supplement_section=supplement_section,
    )
    return rendered, ""
