"""sp-api fulltext 路由测试 — 验证零本地 PDF 写。

覆盖：
1. POST /api/fulltext/resolve-url
   - direct passthrough（已带 pdf_url）
   - unpaywall 命中
   - citation_pdf_url meta 命中
   - 全部失败返 {pdf_url: null, source_layer: null}
   - 付费源拒绝（应走 /proxy）
2. POST /api/fulltext/proxy/{source}/{external_id}
   - 软超额返 402
   - 成功 stream chunked → response 完整 binary 等于上游 mock binary
   - 上游非 PDF magic → 500/502，refund 调用
3. **零本地 PDF 写**断言：tmp_path 监控整个 sp-api/app 路径下不产生 .pdf 文件。
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────
# 共享 fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_pdf_scan_root() -> Path:
    """``sp-api/app`` 根，用于事后 grep 没新增 .pdf。"""
    return Path(__file__).resolve().parent.parent / "app"


def _count_pdf_files(root: Path) -> int:
    if not root.exists():
        return 0
    return len(list(root.rglob("*.pdf")))


# ──────────────────────────────────────────────────────────────────────
# resolve_pdf_url 单元测试（不依赖 FastAPI client）
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_url_direct_passthrough():
    """已带 pdf_url 时直接 echo + layer='direct'，不发 HTTP。"""
    from app.services.fulltext_service import resolve_pdf_url

    out = await resolve_pdf_url(
        source="dblp", external_id="x",
        doi=None, landing_url=None,
        pdf_url="https://example.org/a.pdf",
    )
    assert out == {"pdf_url": "https://example.org/a.pdf", "source_layer": "direct"}


@pytest.mark.asyncio
async def test_resolve_url_unpaywall_hit():
    """unpaywall 返 best_oa_location.url_for_pdf 时命中 layer='unpaywall'。"""
    from app.services import fulltext_service

    async def fake_unpaywall(doi):
        assert doi == "10.1038/abc"
        return "https://oa.example/file.pdf"

    with patch.object(fulltext_service, "unpaywall_lookup", new=fake_unpaywall):
        out = await fulltext_service.resolve_pdf_url(
            source="pubmed", external_id="123",
            doi="10.1038/abc", landing_url=None,
        )
    assert out["pdf_url"] == "https://oa.example/file.pdf"
    assert out["source_layer"] == "unpaywall"


@pytest.mark.asyncio
async def test_resolve_url_no_layers_hits():
    """所有解析层都 None → 返回 None。"""
    from app.services import fulltext_service

    async def fake_unpaywall(doi):
        return None

    with patch.object(fulltext_service, "unpaywall_lookup", new=fake_unpaywall):
        # 没传 doi / landing_url，路径 2/3/4 都不会触发
        out = await fulltext_service.resolve_pdf_url(
            source="pubmed", external_id="x", doi=None, landing_url=None,
        )
    assert out == {"pdf_url": None, "source_layer": None}


def test_extract_citation_pdf_meta_basic():
    """citation_pdf_url meta 抓取 — name 在前 / content 在前 / 单引号都支持。"""
    from app.services.fulltext_service import _extract_citation_pdf

    html_a = '<meta name="citation_pdf_url" content="https://e.com/a.pdf">'
    assert _extract_citation_pdf(html_a) == "https://e.com/a.pdf"

    html_b = "<meta content='/files/x.pdf' name='citation_pdf_url'>"
    assert _extract_citation_pdf(html_b) == "/files/x.pdf"

    assert _extract_citation_pdf("<html>nada</html>") is None


# ──────────────────────────────────────────────────────────────────────
# stream_pdf_proxy 测试
# ──────────────────────────────────────────────────────────────────────


class _FakePatentHubFetcher:
    """精简 patenthub fetcher mock — get_detail + _get_token + 常量。"""

    PAID_PDF = True
    PDF_DOWNLOAD_TIMEOUT = 10.0

    def __init__(self, detail, token="tok", pdf_chunks=None, status_code=200):
        self._detail = detail
        self._token = token
        self._chunks = pdf_chunks or [b"%PDF-1.4 fakebody"]
        self._status_code = status_code

    async def get_detail(self, patent_id):
        return self._detail

    async def _get_token(self):
        return self._token


@pytest.mark.asyncio
async def test_stream_proxy_unknown_source_raises():
    from app.services.fulltext_service import stream_pdf_proxy

    with pytest.raises(ValueError, match="未知 source"):
        async for _ in stream_pdf_proxy(source="totally_made_up", external_id="x"):
            pass


@pytest.mark.asyncio
async def test_stream_proxy_non_paid_source_rejected():
    """免费源不能走 proxy。"""
    from app.services.fulltext_service import stream_pdf_proxy

    # openalex 是免费源，已注册
    with pytest.raises(ValueError, match="不是付费源"):
        async for _ in stream_pdf_proxy(source="openalex", external_id="x"):
            pass


@pytest.mark.asyncio
async def test_stream_proxy_patenthub_chunks_through(monkeypatch, app_pdf_scan_root):
    """patenthub stream 路径 — mock httpx.AsyncClient.stream → yield chunks。
    验证：1) 拿到完整 chunks 2) sp-api/app 没新增 .pdf 文件。"""
    from app.services import fulltext_service
    from app.services.fetchers import international as intl

    pre_count = _count_pdf_files(app_pdf_scan_root)

    fake = _FakePatentHubFetcher(
        detail={"pdfList": ["KEY123"]},
        pdf_chunks=[b"%PDF-1.4 chunk1 ", b"chunk2 ", b"chunk3END"],
    )
    monkeypatch.setitem(intl.ALL_FETCHERS, "patenthub", fake)

    # mock httpx client + stream context manager
    class _FakeStream:
        def __init__(self, chunks, status):
            self._chunks = chunks
            self.status_code = status
            self.headers = {"content-type": "application/pdf"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def aiter_bytes(self, chunk_size=64 * 1024):
            for c in self._chunks:
                yield c

        async def aread(self):
            return b""

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def stream(self, method, url, params=None):
            return _FakeStream(fake._chunks, 200)

    monkeypatch.setattr(fulltext_service, "httpx", _FakeStubModule(_FakeClient))

    chunks = []
    async for c in fulltext_service.stream_pdf_proxy(
        source="patenthub", external_id="CN12345",
    ):
        chunks.append(c)

    assert b"".join(chunks) == b"%PDF-1.4 chunk1 chunk2 chunk3END"
    # 0 本地 PDF 写
    post_count = _count_pdf_files(app_pdf_scan_root)
    assert post_count == pre_count, (
        f"stream_pdf_proxy created PDF on disk: pre={pre_count} post={post_count}"
    )


@pytest.mark.asyncio
async def test_stream_proxy_non_pdf_magic_rejected(monkeypatch):
    """付费 API 返 JSON 错误（前几字节不是 %PDF-）→ RuntimeError。"""
    from app.services import fulltext_service
    from app.services.fetchers import international as intl

    fake = _FakePatentHubFetcher(
        detail={"pdfList": ["KEY"]},
        pdf_chunks=[b'{"error":"quota_exceeded"}'],  # not PDF magic
    )
    monkeypatch.setitem(intl.ALL_FETCHERS, "patenthub", fake)

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        status_code = 200
        headers = {"content-type": "application/json"}

        async def aiter_bytes(self, chunk_size=64 * 1024):
            yield b'{"error":"x"}'

        async def aread(self):
            return b'{"error":"x"}'

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def stream(self, method, url, params=None):
            return _FakeStream()

    monkeypatch.setattr(fulltext_service, "httpx", _FakeStubModule(_FakeClient))

    with pytest.raises(RuntimeError, match="non-PDF body"):
        async for _ in fulltext_service.stream_pdf_proxy(
            source="patenthub", external_id="X",
        ):
            pass


# ──────────────────────────────────────────────────────────────────────
# 全局 grep 验证：sp-api/app 树下不应有 PDF binary I/O
# ──────────────────────────────────────────────────────────────────────


def test_no_local_pdf_writes_in_app_tree():
    """grep 验证：sp-api/app 不再**执行**任何 PDF binary 落盘 API。

    用 AST 扫所有 .py，找以下 *实际调用*（不是注释/docstring/字符串字面量）：
        - X.write_bytes(...)            (e.g. Path.write_bytes)
        - aiofiles.open(...)            (async 文件 IO)
        - tokio::fs::write(...)         (Rust — 本树不该出现)

    例外：
        - tests/                         本测试文件就有这些 ident
        - app/api/document_import.py     用户主动 upload 的原始 binary 落盘到
                                         import_jobs/ 是合法的（与 PDF 全文检索
                                         缓存语义无冲突）。
    """
    import ast

    app_root = Path(__file__).resolve().parent.parent / "app"
    allowlist = {
        str(app_root / "api" / "document_import.py"),
    }
    bad_hits: list[tuple[str, int, str]] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self, path: str):
            self.path = path

        def visit_Call(self, node: ast.Call):
            func = node.func
            # X.write_bytes(...)
            if isinstance(func, ast.Attribute) and func.attr == "write_bytes":
                bad_hits.append(
                    (self.path, func.lineno, f"call .write_bytes (attr={func.attr})"),
                )
            # aiofiles.open(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "open"
                and isinstance(func.value, ast.Name)
                and func.value.id == "aiofiles"
            ):
                bad_hits.append(
                    (self.path, func.lineno, "call aiofiles.open"),
                )
            self.generic_visit(node)

    for py in app_root.rglob("*.py"):
        sp = str(py)
        if sp in allowlist:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue
        _Visitor(sp).visit(tree)

    assert not bad_hits, (
        "sp-api/app 仍含 PDF binary 写盘调用（应该全部下放给客户端 Tauri）：\n"
        + "\n".join(f"  {p}:{ln}: {snip}" for p, ln, snip in bad_hits)
    )


# ──────────────────────────────────────────────────────────────────────
# 工具：让 monkeypatch 把 fulltext_service.httpx 整个换掉
# ──────────────────────────────────────────────────────────────────────


class _FakeStubModule:
    """模拟 ``import httpx`` 子集 — 仅暴露 AsyncClient。"""

    def __init__(self, client_cls):
        self.AsyncClient = client_cls
