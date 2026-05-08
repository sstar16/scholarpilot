"""Import tasks — sp-api 版（仅留临时文件清理）。

vs backend/app/workers/import_tasks.py：
- 删 parse_pdf_metadata / score_imported_document（sp-api 无 markitdown / LLM / scoring）
- 仅保留 cleanup_import_tmp_files（删超过 7 天的导入临时文件）
"""
import logging
import os
import time
from pathlib import Path

from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.import_tasks.cleanup_import_tmp_files")
def cleanup_import_tmp_files() -> dict:
    """每天 03:00 清理 7 天前的临时文件 + 数据库里 cancelled / failed 状态的 job 记录。"""
    base = Path(os.environ.get("PDF_STORAGE_PATH", "/app/data/import_tmp"))
    if not base.exists():
        return {"removed": 0, "reason": "tmp dir not exists"}

    now = time.time()
    threshold = now - 7 * 24 * 3600
    removed = 0
    for f in base.glob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < threshold:
                f.unlink()
                removed += 1
        except OSError as e:
            logger.warning("[cleanup_import_tmp] remove %s failed: %s", f, e)

    return {"removed": removed}
