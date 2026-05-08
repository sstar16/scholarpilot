import os
from pathlib import Path

# 运行时从环境变量读取，ETL 脚本和 Docker 容器各自设置
KB_DATA_DIR = Path(os.environ.get("KB_DATA_DIR", "data/knowledge_base"))

METADATA_DB_PATH = KB_DATA_DIR / "metadata.duckdb"
SEARCH_DB_PATH = KB_DATA_DIR / "search.sqlite"
RELATIONS_DB_PATH = KB_DATA_DIR / "relations.sqlite"
SYNC_STATE_PATH = KB_DATA_DIR / "sync_state.json"

# FTS5 搜索默认参数
FTS_DEFAULT_LIMIT = 200

# ETL 配置
ABSTRACT_PREVIEW_MAX_CHARS = 500
MIN_YEAR = 2000  # 默认只导入 2000 年以后的文献


def ensure_kb_dir():
    """确保 KB 数据目录存在"""
    KB_DATA_DIR.mkdir(parents=True, exist_ok=True)
