import pytest
from app.harness.agents.doc_import_agent import DocImportAgent, PdfMetadata

pytestmark = pytest.mark.asyncio


class _FakeLLMManager:
    """Minimal llm manager double returning a fixed response."""
    def __init__(self, response_text: str):
        self._resp = response_text

    async def generate(self, *args, **kwargs):
        return self._resp


async def test_extract_returns_all_required_fields():
    llm_json = '{"title":"Attention Is All You Need","title_zh":"注意力机制","authors":["Vaswani"],"year":2017,"abstract":"...","doi":"10.0/abc","journal":"NeurIPS","one_line_summary":"Transformer 架构","concept_tags":["attention","transformer"]}'
    agent = DocImportAgent(_FakeLLMManager(llm_json))

    meta = await agent.extract("raw pdf first 3 pages text")

    assert isinstance(meta, PdfMetadata)
    assert meta.title == "Attention Is All You Need"
    assert meta.title_zh == "注意力机制"
    assert meta.year == 2017
    assert "transformer" in meta.concept_tags
    assert meta.doi == "10.0/abc"


async def test_extract_retries_on_malformed_json():
    """LLM returns broken JSON twice, correct on 3rd try."""
    responses = [
        "not json at all",
        "{bad: syntax}",
        '{"title":"ok","authors":["A"],"year":2024,"abstract":"x","one_line_summary":"y","concept_tags":["t"]}',
    ]

    class _RetryLLM:
        def __init__(self):
            self.calls = 0
        async def generate(self, *args, **kwargs):
            r = responses[self.calls]
            self.calls += 1
            return r

    llm = _RetryLLM()
    agent = DocImportAgent(llm)
    meta = await agent.extract("pdf text")

    assert meta.title == "ok"
    assert llm.calls == 3


async def test_extract_gives_up_after_3_retries():
    class _AlwaysBadLLM:
        async def generate(self, *args, **kwargs):
            return "absolutely not json"

    agent = DocImportAgent(_AlwaysBadLLM())
    with pytest.raises(ValueError, match="LLM failed to produce valid JSON"):
        await agent.extract("pdf text")


async def test_extract_empty_input_returns_fallback_without_llm_call():
    class _NeverCalledLLM:
        async def generate(self, *args, **kwargs):
            raise AssertionError("should not be called for empty input")

    agent = DocImportAgent(_NeverCalledLLM())
    meta = await agent.extract("")
    assert meta.title == ""
    assert meta.authors == []
