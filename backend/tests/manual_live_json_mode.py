"""
Live JSON mode 集成测试 —— 真实调用当前激活的 LLM provider。

这是手动脚本（名字不带 test_ 前缀，pytest 不会 pick up）。
在容器里跑：
    docker exec scholarpilot-dev-backend-1 python tests/manual_live_json_mode.py

验证维度：
  T1 - baseline（无 JSON mode）
  T2 - JSON mode + prompt 含 "json"
  T3 - JSON mode + prompt 不含 "json"（触发 auto-append 兜底）
  T4 - IntentAnalysisAgent 端到端
  T5 - ScoringAgent 端到端

消耗：约 3000 tokens 的 DeepSeek 调用（< $0.001）。
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
import uuid


def _unique(text: str) -> str:
    """加 uuid 后缀避免命中 Redis prompt cache。"""
    return f"{text} (req_id={uuid.uuid4().hex[:8]})"


def _print_header(n: int, title: str) -> None:
    print(f"\n{'=' * 62}\n[T{n}] {title}\n{'=' * 62}")


def _print_result(label: str, passed: bool, detail: str = "") -> None:
    mark = "\033[32mOK  \033[0m" if passed else "\033[31mFAIL\033[0m"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    failures = 0

    from app.services.core.llm_config_store import get_llm_manager

    mgr = await get_llm_manager()
    active = mgr.get_active_provider()
    if not active:
        print("ERROR: 没有激活的 LLM provider")
        return 2

    print(f"Active provider: {mgr.active_provider_id}")
    print(f"Active model:    {active.model}")
    print(f"Base URL:        {getattr(active, 'base_url', 'n/a')}")

    # ── T1: baseline ─────────────────────────────────────────────────
    _print_header(1, "baseline (无 JSON mode) —— 可能带前言/后缀")
    prompt = _unique("列出 3 个知名的量子算法，用中文，任意格式即可。")
    r = await mgr.generate_full(prompt, temperature=0.1)
    if r is None:
        _print_result("baseline 返回 None", False)
        failures += 1
    else:
        print(f"  finish_reason={r.finish_reason}")
        print(f"  text preview: {r.text[:160]}...")
        _print_result("baseline 有返回", True,
                      f"{r.usage.total_tokens} tokens, ${r.cost_usd:.6f}")

    # ── T2: JSON mode + prompt 含 "json" ──────────────────────────────
    _print_header(2, "JSON mode + prompt 含 'json' —— 应直接返回合法 JSON")
    prompt = _unique(
        "以 JSON 对象格式返回 3 个量子算法："
        "{\"algorithms\": [{\"name\": \"...\", \"purpose\": \"...\"}]}"
    )
    r = await mgr.generate_full(
        prompt, temperature=0.1,
        response_format={"type": "json_object"},
    )
    if r is None:
        _print_result("JSON mode 返回 None", False)
        failures += 1
    else:
        print(f"  finish_reason={r.finish_reason}")
        print(f"  raw text: {r.text[:300]}")
        passed_call = r.finish_reason not in ("error", None) or bool(r.text)
        _print_result("API 调用成功", passed_call)
        try:
            data = json.loads(r.text)
            _print_result("直接 json.loads 成功", True,
                          f"顶层 keys={list(data.keys())[:3]}")
        except json.JSONDecodeError as e:
            _print_result("直接 json.loads 成功", False, str(e))
            failures += 1

    # ── T3: JSON mode + prompt 不含 "json" ────────────────────────────
    _print_header(3, "JSON mode + prompt 不含 'json' —— 验证 auto-append 兜底")
    prompt = _unique(
        "请给出一个水果清单，key 为 fruits，value 是数组，每项有 name 和 color 两个字段。"
        # 故意不含 "json"
    )
    assert "json" not in prompt.lower(), "测试前提：prompt 必须不含 'json'"
    r = await mgr.generate_full(
        prompt, temperature=0.1,
        response_format={"type": "json_object"},
    )
    if r is None:
        _print_result("没有收到 400 / 其他错误", False,
                      "返回 None（可能是 API 400 'must contain word json'）")
        failures += 1
    else:
        print(f"  finish_reason={r.finish_reason}")
        print(f"  raw text: {r.text[:300]}")
        _print_result("API 没有 400（auto-append 生效）", True)
        try:
            data = json.loads(r.text)
            _print_result("合法 JSON", True,
                          f"顶层 keys={list(data.keys())[:3]}")
        except json.JSONDecodeError as e:
            _print_result("合法 JSON", False, str(e))
            failures += 1

    # ── T4: IntentAnalysisAgent 端到端 ────────────────────────────────
    _print_header(4, "IntentAnalysisAgent.analyze — 端到端真实路径")
    from app.harness.agents.intent_agent import IntentAnalysisAgent

    agent = IntentAnalysisAgent(llm_manager=mgr)
    user_input = f"我想研究量子计算对后量子密码学的影响 ({uuid.uuid4().hex[:6]})"
    try:
        parsed = await agent.analyze(user_input)
    except Exception as e:
        _print_result("analyze 不抛异常", False, repr(e))
        traceback.print_exc()
        failures += 1
        parsed = None
    else:
        _print_result("analyze 不抛异常", True)

    if parsed is None:
        _print_result("返回非 None", False,
                      "两次 attempt 都失败（JSON 解析都没成功）")
        failures += 1
    else:
        is_research = parsed.get("is_research_request", True)
        if not is_research:
            _print_result("识别为研究请求", False,
                          f"被判定为非研究请求: {parsed.get('reply', '')[:60]}")
            failures += 1
        else:
            _print_result(
                "识别为研究请求",
                True,
                f"title={parsed.get('title', '')[:50]} "
                f"domains={parsed.get('domains')} "
                f"confidence={parsed.get('confidence')}",
            )

    # ── T5: ScoringAgent 端到端 ───────────────────────────────────────
    _print_header(5, "ScoringAgent.score_single — 端到端真实路径")
    from app.harness.agents.scoring_agent import ScoringAgent

    sa = ScoringAgent(llm_manager=mgr, max_concurrent=2)
    fake_doc = {
        "title": "Post-Quantum Cryptography: A Survey of Lattice-Based Schemes",
        "abstract": (
            "We review lattice-based cryptographic schemes that are conjectured "
            "to resist attacks by quantum computers running Shor's algorithm. "
            "Coverage includes LWE, Ring-LWE, and Module-LWE constructions."
        ),
        "_relevance_score": 0.5,
    }
    try:
        scored = await sa.score_single(
            fake_doc,
            project_description="量子计算对后量子密码学的影响",
        )
    except Exception as e:
        _print_result("score_single 不抛异常", False, repr(e))
        traceback.print_exc()
        failures += 1
        scored = None
    else:
        _print_result("score_single 不抛异常", True)

    if scored is not None:
        if scored.scoring_failed:
            _print_result(
                "成功打分（未触发 fallback）",
                False,
                "scoring_failed=True —— 传统分数 fallback 被触发",
            )
            failures += 1
        else:
            _print_result(
                "成功打分（未触发 fallback）",
                True,
                f"score={scored.agent_score} rationale={scored.rationale[:60]}",
            )

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'=' * 62}")
    if failures == 0:
        print("\033[32mALL GREEN — JSON mode 端到端工作正常 ✓\033[0m")
        return 0
    print(f"\033[31m{failures} 项失败\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
