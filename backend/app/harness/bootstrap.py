"""
Harness bootstrap — 统一注册 Tool Registry / Hook handlers / Skills。

背景：FastAPI lifespan 只在 backend 进程跑，Celery worker 每个 fork 进程独立。
之前在 main.py 和 celery_app.py::worker_process_init 里各写一套 register 逻辑，
容易"backend 有 8 skill，worker 只有 3 skill"这种分裂。

此模块把所有 register 集中到 `setup_harness()`，两边都调它，永远同步。

幂等：进程级 _setup_done flag 避免 HookEngine.register 追加重复 handler。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_setup_done = False


def setup_harness() -> dict:
    """注册全部 harness 组件。多次调用安全（第二次跳过）。"""
    global _setup_done
    if _setup_done:
        return _current_counts()

    # 延迟 import 避免模块加载顺序问题
    from app.harness.tool_registry import init_tool_registry
    from app.harness.hook_engine import HookEngine
    from app.harness.hooks.logging_hook import register_logging_hooks
    from app.harness.hooks.metrics_hook import register_metrics_hooks
    from app.harness.hooks.workbench_hook import register_workbench_hooks
    from app.harness.hooks.skill_recommender_hook import register_skill_recommender_hook
    from app.harness.hooks.kg_refresh_hook import register_kg_refresh_hook
    from app.harness.hooks.summary_metrics_hook import register_summary_metrics_hook
    from app.harness.skill_registry import SkillRegistry
    from app.harness.skills import (
        deep_dive, trend_spotter, gap_finder,
        # B3/C1: 新增
        export_bibtex, citation_network, methodology_comparison,
        emerging_topics, quality_audit,
    )

    tool_registry = init_tool_registry()
    hook_engine = HookEngine.get_instance()

    # 观测层（logging/metrics/workbench）
    register_logging_hooks(hook_engine)
    register_metrics_hooks(hook_engine)
    register_workbench_hooks(hook_engine)
    # 业务层（skill 推荐 / KG 刷新 / 摘要统计）
    register_skill_recommender_hook(hook_engine)
    register_kg_refresh_hook(hook_engine)
    register_summary_metrics_hook(hook_engine)

    skill_registry = SkillRegistry.get_instance()
    for mod in (
        deep_dive, trend_spotter, gap_finder,
        export_bibtex, citation_network, methodology_comparison,
        emerging_topics, quality_audit,
    ):
        skill_registry.register(mod.DEFINITION, mod.execute)

    _setup_done = True
    counts = {
        "tools": tool_registry.enabled_count,
        "hooks": hook_engine.handler_count,
        "skills": skill_registry.skill_count,
    }
    logger.info(
        "[Harness] bootstrap done — %d tools | %d hooks | %d skills",
        counts["tools"], counts["hooks"], counts["skills"],
    )
    return counts


def _current_counts() -> dict:
    """给二次调用（幂等 return）用的快照。"""
    from app.harness.tool_registry import init_tool_registry
    from app.harness.hook_engine import HookEngine
    from app.harness.skill_registry import SkillRegistry
    try:
        tools = init_tool_registry().enabled_count
    except Exception:
        tools = 0
    return {
        "tools": tools,
        "hooks": HookEngine.get_instance().handler_count,
        "skills": SkillRegistry.get_instance().skill_count,
    }
