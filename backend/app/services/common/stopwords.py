"""
统一停用词模块 —— 合并之前分散在三处的英/中停用词定义。

设计原则：
- 分语言 + 分用途维护（grammar word / academic noise）
- 只收"基本不携带研究方向信息"的词
- **不收**"在某些学科里可能是核心"的词（如 high/low/large/small 在材料/物理是核心修饰词；
  drops/100/per 等过拟合项之前被错误加入，此次清理移除）

调用方：
- source_query_adapters._top_words → 英文 token 过滤
- source_query_adapters.ChineseSourceAdapter.adapt → 中文 fallback 过滤
- query_builder._extract_core_query → 中英混合 fallback 过滤
"""
from __future__ import annotations


# 中文 grammar word（虚词，不承载研究方向信息）
ZH_GRAMMAR = frozenset({
    "的", "了", "在", "是", "和", "与", "或", "及", "等", "并", "而",
    "我们", "他们", "它", "一个", "这", "那",
})

# 中文学术论文套话词
ZH_ACADEMIC_NOISE = frozenset({
    "研究", "开发", "项目", "本文", "本研究",
    "方法", "分析", "通过", "进行", "实现", "提出", "探讨", "讨论",
    "目的", "结果", "结论", "综述", "综合",
})

# 完整中文停用词集（给 adapter / query_builder 用的唯一入口）
ZH_STOPWORDS: frozenset[str] = ZH_GRAMMAR | ZH_ACADEMIC_NOISE


# 英文学术论文套话词
# 注：不含 the/a/of/for 这类 1-2 字母词，min_len=3 已自动过滤
# 注：不含 high/low/large/small - 在材料/物理/能源领域是核心修饰词
# 注：不含 per/drops/drop/100 - 过拟合历史噪声项，已清理
EN_ACADEMIC_NOISE = frozenset({
    "based", "using", "study", "studies", "analysis",
    "method", "methods", "approach", "research", "paper",
    "novel", "new", "improved", "advanced",
    "show", "shows", "propose", "proposed",
    "first", "second", "third",
    "development", "system", "design",
})

# 完整英文停用词集（给 adapter 用的唯一入口）
EN_STOPWORDS: frozenset[str] = EN_ACADEMIC_NOISE
