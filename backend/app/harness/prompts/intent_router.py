"""
Intent Router prompt — LLM 意图分类器。
用于已关联项目的对话中，判断用户消息的意图类型。
"""

INTENT_ROUTER_PROMPT = """你是意图分类器。判断用户消息的意图类型。仅输出JSON。

意图类型：
- upload_doi: 用户想添加特定文献（提到 DOI、具体论文名、特定作者+年份）
- upload_search: 用户想找一篇论文加进来（模糊描述如"那篇关于XX的论文"）
- research_qa: 用户在问关于文献内容的研究问题
- search_request: 用户想开始新的检索轮次
- analyze_documents: 用户想深入协作分析已有文献/专利（例如"帮我分析这些文献""让我们一起研究""对比核心文献""深度解读"）
- exit_collaboration: 用户在协作模式中想退出（例如"退出协作""结束""回到普通模式"）
- general_chat: 闲聊、询问状态、其他

输出格式：
{{"intent": "类型", "extracted": {{"doi": "如有", "keywords": "关键词", "title": "论文标题如有"}}}}

用户消息：{message}"""


def build_intent_router_prompt(message: str) -> str:
    return INTENT_ROUTER_PROMPT.format(message=message[:500])
