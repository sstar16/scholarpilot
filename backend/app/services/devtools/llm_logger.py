"""
LLM call logging wrapper for DevTools.
Monkey-patches LLMProviderManager.generate() to capture all LLM calls.
"""
import time
import logging
from typing import Optional

logger = logging.getLogger("devtools.llm_logger")


def patch_llm_manager(manager) -> None:
    """Wrap manager.generate() to log every LLM call to DevTools."""
    if getattr(manager, "_devtools_patched", False):
        return

    original_generate = manager.generate

    async def logged_generate(
        prompt: str,
        temperature: float = 0.1,
        **kwargs,
    ) -> Optional[str]:
        from app.services.devtools.log_writer import log_buffer

        provider = manager.get_active_provider()
        provider_id = manager.active_provider_id or "unknown"
        model_name = getattr(provider, "model", "unknown") if provider else "unknown"

        start = time.time()
        error_trace = None
        result = None
        try:
            result = await original_generate(prompt, temperature, **kwargs)
            return result
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            prompt_len = len(prompt)
            result_len = len(result) if result else 0
            level = "ERROR" if error_trace else "INFO"

            log_buffer.add({
                "level": level,
                "source": "llm",
                "category": f"{provider_id}/{model_name}",
                "message": f"LLM generate → {provider_id}/{model_name} ({duration_ms}ms, prompt={prompt_len}c, result={result_len}c)",
                "context": {
                    "provider": provider_id,
                    "model": model_name,
                    "temperature": temperature,
                    "prompt_chars": prompt_len,
                    "result_chars": result_len,
                },
                "duration_ms": duration_ms,
                "error_trace": error_trace,
            })

    manager.generate = logged_generate
    manager._devtools_patched = True
    logger.info("LLM manager patched for DevTools logging")
