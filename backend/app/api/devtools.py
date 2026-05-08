"""
DevTools API — log queries, stats, WebSocket real-time push, source testing.
All endpoints require admin access.
"""
import asyncio
import json
import logging
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import require_admin
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devtools", tags=["devtools"])


# ──────────────── REST Endpoints ────────────────


@router.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    source: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    round_id: Optional[str] = None,
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Paginated log query with filters."""
    conditions = []
    params = {}

    if level:
        conditions.append("level = :level")
        params["level"] = level.upper()
    if source:
        conditions.append("source = :source")
        params["source"] = source
    if category:
        conditions.append("category ILIKE :category")
        params["category"] = f"%{category}%"
    if search:
        conditions.append("message ILIKE :search")
        params["search"] = f"%{search}%"
    if round_id:
        conditions.append("round_id = :round_id")
        params["round_id"] = round_id
    if from_ts:
        conditions.append("created_at >= :from_ts")
        params["from_ts"] = from_ts
    if to_ts:
        conditions.append("created_at <= :to_ts")
        params["to_ts"] = to_ts

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    # Count
    count_result = await db.execute(
        text(f"SELECT count(*) FROM dev_logs WHERE {where_clause}"), params
    )
    total = count_result.scalar()

    # Query
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset
    result = await db.execute(
        text(f"""
            SELECT id, created_at, level, source, category, message, context,
                   round_id, project_id, duration_ms, error_trace
            FROM dev_logs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()
    items = [
        {
            "id": row["id"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "level": row["level"],
            "source": row["source"],
            "category": row["category"],
            "message": row["message"],
            "context": row["context"],
            "round_id": str(row["round_id"]) if row["round_id"] else None,
            "project_id": str(row["project_id"]) if row["project_id"] else None,
            "duration_ms": row["duration_ms"],
            "error_trace": row["error_trace"],
        }
        for row in rows
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Dashboard stats for the last hour."""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    result = await db.execute(
        text("""
            SELECT
                count(*) FILTER (WHERE level = 'ERROR') AS error_count,
                count(*) FILTER (WHERE source = 'http') AS request_count,
                count(*) FILTER (WHERE source = 'llm') AS llm_count,
                count(*) FILTER (WHERE source = 'celery') AS celery_count,
                count(*) AS total_count,
                avg(duration_ms) FILTER (WHERE source = 'http') AS avg_request_ms
            FROM dev_logs
            WHERE created_at >= :since
        """),
        {"since": one_hour_ago},
    )
    row = result.mappings().first()

    # Sparkline: request counts per 5-minute bucket
    sparkline_result = await db.execute(
        text("""
            SELECT date_trunc('minute', created_at) -
                   (EXTRACT(minute FROM created_at)::int % 5) * interval '1 minute' AS bucket,
                   count(*) AS cnt
            FROM dev_logs
            WHERE source = 'http' AND created_at >= :since
            GROUP BY bucket
            ORDER BY bucket
        """),
        {"since": one_hour_ago},
    )
    sparkline = [
        {"time": r["bucket"].isoformat(), "count": r["cnt"]}
        for r in sparkline_result.mappings().all()
    ]

    return {
        "error_count": row["error_count"] or 0,
        "request_count": row["request_count"] or 0,
        "llm_count": row["llm_count"] or 0,
        "celery_count": row["celery_count"] or 0,
        "total_count": row["total_count"] or 0,
        "avg_request_ms": round(row["avg_request_ms"] or 0, 1),
        "sparkline": sparkline,
    }


@router.get("/sources")
async def get_source_latency(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Source latency heatmap — per-category average duration over time buckets."""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await db.execute(
        text("""
            SELECT category,
                   date_trunc('minute', created_at) -
                       (EXTRACT(minute FROM created_at)::int % 5) * interval '1 minute' AS bucket,
                   avg(duration_ms) AS avg_ms,
                   count(*) AS call_count,
                   count(*) FILTER (WHERE level = 'ERROR') AS error_count
            FROM dev_logs
            WHERE duration_ms IS NOT NULL
              AND created_at >= :since
              AND category IS NOT NULL
            GROUP BY category, bucket
            ORDER BY bucket DESC
            LIMIT 200
        """),
        {"since": one_hour_ago},
    )
    rows = result.mappings().all()
    return [
        {
            "source": r["category"],
            "bucket": r["bucket"].isoformat() if r["bucket"] else None,
            "avg_ms": round(r["avg_ms"] or 0, 1),
            "call_count": r["call_count"],
            "error_count": r["error_count"],
        }
        for r in rows
    ]


@router.delete("/logs")
async def delete_logs(
    before_hours: int = Query(0, ge=0, description="Delete logs older than N hours. 0 = delete all"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Delete logs. before_hours=0 deletes all, otherwise deletes logs older than N hours."""
    if before_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=before_hours)
        result = await db.execute(
            text("DELETE FROM dev_logs WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
    else:
        result = await db.execute(text("DELETE FROM dev_logs"))
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/log-tree")
async def get_log_tree(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Category tree structure — grouped counts by source and category."""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await db.execute(
        text("""
            SELECT source, category, level, count(*) AS cnt
            FROM dev_logs
            WHERE created_at >= :since
            GROUP BY source, category, level
            ORDER BY source, category, level
        """),
        {"since": one_hour_ago},
    )
    rows = result.mappings().all()

    # Build tree
    tree = {}
    for r in rows:
        src = r["source"]
        cat = r["category"] or "uncategorized"
        lvl = r["level"]
        if src not in tree:
            tree[src] = {"total": 0, "categories": {}, "levels": {}}
        tree[src]["total"] += r["cnt"]
        tree[src]["levels"][lvl] = tree[src]["levels"].get(lvl, 0) + r["cnt"]
        if cat not in tree[src]["categories"]:
            tree[src]["categories"][cat] = {"total": 0, "levels": {}}
        tree[src]["categories"][cat]["total"] += r["cnt"]
        tree[src]["categories"][cat]["levels"][lvl] = (
            tree[src]["categories"][cat]["levels"].get(lvl, 0) + r["cnt"]
        )

    return tree


# ──────────────── Source Registry & Testing ────────────────


class SourceTestRequest(BaseModel):
    source_id: str
    query: str
    max_results: int = 5
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    language: Optional[str] = None


class SourceConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    credentials: Optional[Dict[str, str]] = None
    proxy: Optional[str] = None          # per-source proxy URL
    global_proxy: Optional[str] = None   # 全局代理 URL


@router.get("/source-registry")
async def get_source_registry(
    _admin: User = Depends(require_admin),
):
    """返回所有数据源的完整信息：元数据 + 运行时统计 + 启用状态 + 脱敏凭证。"""
    from app.services.fetchers.base import FetcherRegistry
    from app.services.fetchers.international import ALL_FETCHERS
    from app.harness.tool_registry import ToolRegistry
    from app.services.source_config_store import (
        SOURCE_CREDENTIALS, get_effective_disabled, get_credential, mask_value,
        get_source_config,
    )

    registry = ToolRegistry.get_instance()
    disabled = await get_effective_disabled()
    config = await get_source_config()
    global_proxy = config.get("global_proxy", "")
    proxy_overrides = config.get("proxy_overrides", {})

    sources = []
    for sid, meta in FetcherRegistry.SOURCES.items():
        has_fetcher = sid in ALL_FETCHERS
        tool = registry.get_tool(sid)

        # 凭证信息
        required_keys = SOURCE_CREDENTIALS.get(sid, [])
        configured = {}
        for key in required_keys:
            val = await get_credential(sid, key)
            configured[key] = mask_value(val) if val else ""

        # 统计
        stats = {
            "total_invocations": tool.total_invocations if tool else 0,
            "successful_invocations": tool.successful_invocations if tool else 0,
            "avg_latency_ms": tool.avg_latency_ms if tool else 0,
            "reliability": round(tool.reliability, 3) if tool else 1.0,
        }

        sources.append({
            "source_id": sid,
            "name": meta["name"],
            "description": meta.get("description", ""),
            "doc_type": meta.get("doc_type", "paper"),
            "category": meta.get("category", "literature"),
            "language": meta.get("language", "en"),
            "phase": meta.get("phase", 1),
            "enabled": has_fetcher and sid not in disabled,
            "has_fetcher": has_fetcher,
            "credentials": {"required": required_keys, "configured": configured},
            "stats": stats,
            "proxy": proxy_overrides.get(sid, ""),
        })

    return {"sources": sources, "global_proxy": global_proxy}


@router.post("/source-test")
async def test_source(
    req: SourceTestRequest,
    _admin: User = Depends(require_admin),
):
    """直接调用 fetcher 执行测试检索，返回原始结果 + 计时 + 错误详情。"""
    from app.services.fetchers.international import ALL_FETCHERS
    from app.harness.tool_registry import ToolRegistry

    fetcher = ALL_FETCHERS.get(req.source_id)
    if not fetcher:
        return {
            "source_id": req.source_id,
            "status": "error",
            "count": 0,
            "elapsed_ms": 0,
            "results": [],
            "error": f"No fetcher found for '{req.source_id}'",
            "error_trace": None,
        }

    start = time.monotonic()
    try:
        results = await asyncio.wait_for(
            fetcher.fetch(
                query=req.query,
                max_results=req.max_results,
                year_from=req.year_from,
                year_to=req.year_to,
                language=req.language,
            ),
            timeout=45.0,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        ToolRegistry.get_instance().record_result(req.source_id, True, elapsed)
        return {
            "source_id": req.source_id,
            "status": "ok",
            "count": len(results),
            "elapsed_ms": elapsed,
            "results": results,
            "error": None,
            "error_trace": None,
        }
    except asyncio.TimeoutError:
        elapsed = int((time.monotonic() - start) * 1000)
        ToolRegistry.get_instance().record_result(req.source_id, False, elapsed)
        return {
            "source_id": req.source_id,
            "status": "timeout",
            "count": 0,
            "elapsed_ms": elapsed,
            "results": [],
            "error": f"Timeout after 45s",
            "error_trace": None,
        }
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        ToolRegistry.get_instance().record_result(req.source_id, False, elapsed)
        return {
            "source_id": req.source_id,
            "status": "error",
            "count": 0,
            "elapsed_ms": elapsed,
            "results": [],
            "error": str(e),
            "error_trace": traceback.format_exc(),
        }


@router.patch("/source-config/{source_id}")
async def update_source_config(
    source_id: str,
    body: SourceConfigUpdate,
    _admin: User = Depends(require_admin),
):
    """修改运行时配置：启用/禁用、凭证更新。"""
    from app.services.source_config_store import get_source_config, save_source_config
    from app.harness.tool_registry import ToolRegistry

    config = await get_source_config()
    disabled_list = list(config.get("disabled_overrides", []))
    enabled_list = list(config.get("enabled_overrides", []))
    cred_overrides = dict(config.get("credential_overrides", {}))

    if body.enabled is not None:
        if body.enabled:
            # 启用：加入 enabled_overrides（覆盖 env 禁用），从 disabled 移除
            if source_id in disabled_list:
                disabled_list.remove(source_id)
            if source_id not in enabled_list:
                enabled_list.append(source_id)
        else:
            # 禁用：加入 disabled_overrides，从 enabled 移除
            if source_id in enabled_list:
                enabled_list.remove(source_id)
            if source_id not in disabled_list:
                disabled_list.append(source_id)

        # 同步更新 ToolRegistry
        tool = ToolRegistry.get_instance().get_tool(source_id)
        if tool:
            tool.enabled = body.enabled

    if body.credentials:
        if source_id not in cred_overrides:
            cred_overrides[source_id] = {}
        for k, v in body.credentials.items():
            if v:  # 空字符串不覆盖
                cred_overrides[source_id][k] = v

    # 代理配置
    proxy_overrides = dict(config.get("proxy_overrides", {}))
    if body.proxy is not None:
        if body.proxy.strip():
            proxy_overrides[source_id] = body.proxy.strip()
        elif source_id in proxy_overrides:
            del proxy_overrides[source_id]  # 清空 = 删除 per-source 覆盖

    if body.global_proxy is not None:
        config["global_proxy"] = body.global_proxy.strip()

    config["disabled_overrides"] = disabled_list
    config["enabled_overrides"] = enabled_list
    config["credential_overrides"] = cred_overrides
    config["proxy_overrides"] = proxy_overrides
    await save_source_config(config)

    return {"success": True, "source_id": source_id}


@router.post("/source-registry/{source_id}/reset-stats")
async def reset_source_stats(
    source_id: str,
    _admin: User = Depends(require_admin),
):
    """重置某源的运行时统计。"""
    from app.harness.tool_registry import ToolRegistry

    tool = ToolRegistry.get_instance().get_tool(source_id)
    if not tool:
        return {"success": False, "error": f"Unknown source: {source_id}"}

    tool.total_invocations = 0
    tool.successful_invocations = 0
    tool.total_latency_ms = 0
    return {"success": True, "source_id": source_id}


# ──────────────── WebSocket ────────────────


@router.websocket("/ws")
async def devtools_ws(websocket: WebSocket, token: str = Query(...)):
    """Real-time log stream via WebSocket. Requires admin JWT token."""
    # Auth check
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token")
            return
    except JWTError:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Check is_admin
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user or not user.is_admin:
            await websocket.close(code=4003, reason="Admin required")
            return

    await websocket.accept()

    # Client-side filter
    client_filter = {}

    # Subscribe to Redis Pub/Sub
    import redis.asyncio as aioredis
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("devtools:logs")

    try:
        # Task to read client messages (filter updates)
        async def read_client():
            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    if "filter" in msg:
                        client_filter.update(msg["filter"])
            except (WebSocketDisconnect, Exception):
                pass

        client_task = asyncio.create_task(read_client())

        # Push logs from Redis to client
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                log_data = json.loads(message["data"])

                # Apply client filter
                if client_filter:
                    if client_filter.get("level") and log_data.get("level") != client_filter["level"]:
                        continue
                    if client_filter.get("source") and log_data.get("source") != client_filter["source"]:
                        continue

                await websocket.send_text(json.dumps(log_data, ensure_ascii=False))
            else:
                await asyncio.sleep(0.1)

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        client_task.cancel()
        await pubsub.unsubscribe("devtools:logs")
        await pubsub.close()
        await redis_client.close()


# ──────────────── Local Knowledge Base ────────────────


@router.get("/kb/stats")
async def get_kb_stats(user: User = Depends(require_admin)):
    """本地知识库统计信息"""
    import json
    from pathlib import Path

    try:
        from app.knowledge_base.config import KB_DATA_DIR
        from app.knowledge_base.metadata_store import MetadataStore
        from app.knowledge_base.search_index import SearchIndex
        from app.knowledge_base.relations import RelationStore
    except ImportError:
        return {"available": False, "message": "KB module not installed"}

    kb_dir = KB_DATA_DIR
    if not (kb_dir / "metadata.duckdb").exists():
        return {"available": False, "message": "KB data files not found"}

    try:
        metadata = MetadataStore(kb_dir / "metadata.duckdb")
        metadata.init_schema()

        search = SearchIndex(kb_dir / "search.sqlite")
        search.init_schema()

        total_works = metadata.count()
        fts_count = search.count()

        # Stats by year / language / type / topic
        # 用 MetadataStore._fetch_as_dicts 避免依赖 pandas（fetchdf 需要 pandas，容器里没装）
        by_year = metadata._fetch_as_dicts(
            "SELECT publication_year, COUNT(*) as count FROM works "
            "WHERE publication_year IS NOT NULL "
            "GROUP BY publication_year ORDER BY publication_year DESC LIMIT 20"
        )
        by_language = metadata._fetch_as_dicts(
            "SELECT language, COUNT(*) as count FROM works "
            "WHERE language IS NOT NULL "
            "GROUP BY language ORDER BY count DESC LIMIT 10"
        )
        by_type = metadata._fetch_as_dicts(
            "SELECT type, COUNT(*) as count FROM works "
            "WHERE type IS NOT NULL "
            "GROUP BY type ORDER BY count DESC LIMIT 10"
        )
        by_domain = metadata._fetch_as_dicts(
            "SELECT primary_domain_name, COUNT(*) as count FROM works "
            "WHERE primary_domain_name IS NOT NULL "
            "GROUP BY primary_domain_name ORDER BY count DESC LIMIT 15"
        )
        top_topics = metadata._fetch_as_dicts(
            "SELECT primary_topic_name, COUNT(*) as count FROM works "
            "WHERE primary_topic_name IS NOT NULL "
            "GROUP BY primary_topic_name ORDER BY count DESC LIMIT 20"
        )

        # Citation count
        citation_count = 0
        relations_path = kb_dir / "relations.sqlite"
        if relations_path.exists():
            relations = RelationStore(relations_path)
            relations.init_schema()
            citation_count = relations.citation_count()
            relations.close()

        # File sizes
        file_sizes = {}
        for name in ["metadata.duckdb", "search.sqlite", "relations.sqlite"]:
            p = kb_dir / name
            if p.exists():
                file_sizes[name] = round(p.stat().st_size / 1e6, 1)

        # Sync state
        sync_state = {}
        sync_path = kb_dir / "sync_state.json"
        if sync_path.exists():
            sync_state = json.loads(sync_path.read_text())

        metadata.close()
        search.close()

        return {
            "available": True,
            "total_works": total_works,
            "fts_indexed": fts_count,
            "citation_count": citation_count,
            "by_year": by_year,
            "by_language": by_language,
            "by_type": by_type,
            "by_domain": by_domain,
            "top_topics": top_topics,
            "file_sizes": file_sizes,
            "sync_state": sync_state,
        }
    except Exception as e:
        logger.error("KB stats error: %s", e)
        return {"available": False, "message": str(e)}


# ── Telemetry dashboard data ───────────────────────────────────────────────


@router.get("/telemetry")
async def get_telemetry(
    days: int = Query(14, ge=1, le=90),
    recent: int = Query(50, ge=0, le=500),
    _admin: User = Depends(require_admin),
):
    """Aggregated stale-hint funnel for the DevTools dashboard.

    Reads ``TELEMETRY_JSONL_PATH`` (default ``/app/data/telemetry.jsonl``),
    filters to last ``days`` days, and returns per-day funnel + the most
    recent ``recent`` raw events for the live feed pane.
    """
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    path_str = os.getenv("TELEMETRY_JSONL_PATH") or "/app/data/telemetry.jsonl"
    path = Path(path_str)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records: list[dict] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = str(rec.get("ts", ""))
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        continue
                    if ts < cutoff:
                        continue
                    records.append(rec)
        except OSError as e:
            logger.warning("[devtools/telemetry] read failed: %s", e)

    from scripts.analyze_telemetry import analyse  # local to keep cold path
    funnel = analyse(records)

    return {
        "available": path.exists(),
        "path": str(path),
        "window_days": days,
        "total_events": len(records),
        "by_day": [
            {"date": d, **stats} for d, stats in funnel.items()
        ],
        "recent_events": records[-recent:] if recent else [],
    }


# ──────────────── M3 Cleanup expired round cache ────────────────
# 自动 beat schedule 已禁用（celery_app.py F1 注释），这里给 admin 手动触发 + 预览。


@router.get("/cleanup-rounds/preview")
async def cleanup_rounds_preview(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """看当前 expired_at < NOW() 的 round 数量 + cleanup 调度状态。"""
    from datetime import datetime, timezone
    from sqlalchemy import select, func
    from app.models.search_round import SearchRound

    now = datetime.now(timezone.utc)
    expired_q = await db.execute(
        select(func.count(SearchRound.id)).where(SearchRound.expires_at < now)
    )
    expired_count = expired_q.scalar() or 0

    has_ttl_q = await db.execute(
        select(func.count(SearchRound.id)).where(SearchRound.expires_at.isnot(None))
    )
    has_ttl_count = has_ttl_q.scalar() or 0

    total_q = await db.execute(select(func.count(SearchRound.id)))
    total = total_q.scalar() or 0

    return {
        "expired_count": expired_count,
        "has_ttl_count": has_ttl_count,
        "total_rounds": total,
        "auto_schedule_enabled": False,  # M3 F1 禁用
        "auto_schedule_note": "自动 beat 已禁用（celery_app.py），改为 DevTools 手动触发。",
        "now_utc": now.isoformat(),
    }


@router.post("/cleanup-rounds/run")
async def cleanup_rounds_run(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """手动触发清理过期 round。同步跑（数据量小不会卡）。"""
    from app.workers.cleanup_tasks import _cleanup_async

    result = await _cleanup_async(db)
    logger.info("[devtools] manual cleanup-rounds by admin: deleted=%d", result.get("deleted", 0))
    return {**result, "triggered_by": "manual_admin"}
