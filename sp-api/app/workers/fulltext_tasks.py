"""Celery tasks for fulltext download — sp-api **零本地 PDF 写**改造后已废弃。

历史：早期 sp-api 通过 Celery 后台批量下载 PDF + 经 SSE 推 base64 给客户端。
2026-05-08 改造：sp-api 不再落盘 PDF，所有下载逻辑全部下放给客户端 Tauri Rust。
- A 类 OA 直链 / B 类 landing-meta：客户端 ``pdf_fetcher.rs`` 自抓
- C 类付费源：``POST /api/fulltext/proxy/{source}/{id}`` 流式转发，不写 disk

本文件保留为空 module 是为了：
1. ``celery_app.py`` 的 ``include=[..., "app.workers.fulltext_tasks", ...]``
   不至于 ``ModuleNotFoundError``
2. 留个 anchor 万一以后真要异步化某个**纯 metadata** 任务（不写 binary）
"""
import logging

logger = logging.getLogger(__name__)

# 故意不注册任何 @celery_app.task。Celery autodiscovery 不会报错，
# 只会发现这个 module 是空的。

logger.debug(
    "[sp-api] app.workers.fulltext_tasks loaded as no-op stub "
    "(client now owns all PDF I/O; see app/api/fulltext.py)"
)
