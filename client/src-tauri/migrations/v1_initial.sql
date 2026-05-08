-- M2 v1: ScholarPilot 客户端本地 schema
-- 与 backend/app/models/ 字段对齐，去掉云端独有字段（user_id / 邀请码 / 付费源 etc.）。
-- 时间统一 INTEGER unix-ms；JSON 字段统一 TEXT；UUID 统一 TEXT。

-- 元信息：schema 版本 + 客户端配置标记（feature flags / first-run / 等）
CREATE TABLE IF NOT EXISTS meta_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

-- 项目（对应 backend.projects）
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,                    -- backend project.id (UUID 字符串)
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT 'other',
    domains_json TEXT,                      -- JSON array, e.g. ["biology","chemistry"]
    search_config_json TEXT,
    current_round INTEGER NOT NULL DEFAULT 0,
    max_rounds INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',  -- active|monitoring|archived
    research_note_md TEXT NOT NULL DEFAULT '',
    research_note_updated_at INTEGER,
    research_note_updated_by TEXT,          -- 'user' | 'ai'
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_synced_at INTEGER                  -- 最近从云端拉成功的时间 (ms)
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at);

-- 检索轮次（对应 backend.search_rounds）
CREATE TABLE IF NOT EXISTS search_rounds (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    -- pending | awaiting_keywords | searching | scoring | saving | summarizing
    -- | awaiting_feedback | complete | partial_complete | failed
    -- | cancelled | closed | closed_no_feedback
    time_horizon_years INTEGER,
    max_results INTEGER NOT NULL DEFAULT 10,
    language_scope TEXT NOT NULL DEFAULT 'chinese',
    sources_used_json TEXT,
    search_queries_json TEXT,
    total_candidates INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    source_stats_json TEXT,
    progress REAL NOT NULL DEFAULT 0.0,
    progress_message TEXT NOT NULL DEFAULT '',
    started_at INTEGER,
    completed_at INTEGER,
    cancelled_reason TEXT,
    cancelled_at INTEGER,
    partial_answer_json TEXT,
    partial_completed_at INTEGER,
    created_at INTEGER NOT NULL,
    last_synced_at INTEGER,
    UNIQUE (project_id, round_number)
);
CREATE INDEX IF NOT EXISTS idx_rounds_project ON search_rounds(project_id);
CREATE INDEX IF NOT EXISTS idx_rounds_status ON search_rounds(status);

-- 文献（对应 backend.documents — 全局，多 round 共用）
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,                 -- paper | patent | preprint | news | conference
    title TEXT NOT NULL,
    title_zh TEXT,
    authors TEXT,
    abstract TEXT,
    publication_date TEXT,                  -- ISO date 'YYYY-MM-DD' (跟 backend DocumentOut 协议对齐)
    url TEXT,
    doi TEXT,
    journal TEXT,
    citation_count INTEGER NOT NULL DEFAULT 0,
    pdf_url TEXT,
    -- 全文（双格式）
    fulltext_status TEXT NOT NULL DEFAULT 'not_attempted',
    fulltext_path TEXT,                     -- backend 字段，保留兼容
    fulltext_pdf_path TEXT,
    fulltext_pdf_status TEXT NOT NULL DEFAULT 'not_attempted',
    fulltext_html_path TEXT,
    fulltext_html_status TEXT NOT NULL DEFAULT 'not_attempted',
    fulltext_text TEXT,
    -- 客户端独有：本地 PDF 副本路径（相对 app data root）
    pdf_local_path TEXT,
    html_local_path TEXT,
    fulltext_local_path TEXT,
    -- AI 字段
    ai_summary TEXT,
    ai_key_points_json TEXT,
    ai_relevance_reason TEXT,
    ai_summary_source TEXT NOT NULL DEFAULT 'not_generated',
    ai_summary_user TEXT,
    ai_key_points_user_json TEXT,
    countries_json TEXT,
    quality_score REAL,
    one_line_summary TEXT,
    one_line_summary_user TEXT,
    concept_tags_json TEXT,
    probe_cache_json TEXT,
    content_hash TEXT,
    import_source TEXT NOT NULL DEFAULT 'search',
    imported_at INTEGER,
    created_at INTEGER NOT NULL,
    last_synced_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_pub_date ON documents(publication_date);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_import_source ON documents(import_source);

-- round ↔ document 多对多 (对应 backend.round_documents)
CREATE TABLE IF NOT EXISTS round_documents (
    id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES search_rounds(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    rank_in_round INTEGER,
    initial_score REAL,
    agent_score REAL,
    agent_rationale TEXT,
    one_line_summary TEXT,
    below_cutoff INTEGER NOT NULL DEFAULT 0,  -- SQLite 没 BOOL，用 0/1
    UNIQUE (round_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_round_documents_round ON round_documents(round_id);
CREATE INDEX IF NOT EXISTS idx_round_documents_document ON round_documents(document_id);

-- 文档分桶（4-bucket 反馈）
CREATE TABLE IF NOT EXISTS document_classifications (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    bucket TEXT NOT NULL,                   -- very_relevant | relevant | uncertain | irrelevant
    reason TEXT,
    classified_at INTEGER NOT NULL,
    last_synced_at INTEGER,
    PRIMARY KEY (project_id, document_id)
);

-- 对话会话（对应 backend.conversation_sessions，每个 project 至多一条 active）
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    current_state TEXT NOT NULL DEFAULT 'idle',
    state_data_json TEXT,
    search_mode TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_synced_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON conversation_sessions(project_id);

-- 对话消息（拆出来不放 conversation_sessions.messages JSON 里 — 写入更高频 + 单条编辑更便宜）
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                     -- user | assistant | system
    content_md TEXT NOT NULL,
    rich_data_json TEXT,
    created_at INTEGER NOT NULL,
    seq INTEGER NOT NULL                    -- 同 session 内单调递增，用于排序
);
CREATE INDEX IF NOT EXISTS idx_messages_session_seq ON messages(session_id, seq);

-- 笔记本页 (对应 backend.research_note_pages)
CREATE TABLE IF NOT EXISTS research_note_pages (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '未命名页',
    body_md TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    updated_by TEXT,                        -- 'user' | 'ai'
    created_at INTEGER NOT NULL,
    last_synced_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_notebook_project ON research_note_pages(project_id, sort_order);

-- 客户端配置（key/value，不入 keychain — 不敏感）
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

-- 同步状态（每条记录的 dirty / version 标记，M7 加密同步会扩展）
CREATE TABLE IF NOT EXISTS sync_state (
    entity_type TEXT NOT NULL,              -- project | round | document | classification | message | notebook_page | session
    entity_id TEXT NOT NULL,
    local_version INTEGER NOT NULL DEFAULT 0,
    remote_version INTEGER NOT NULL DEFAULT 0,
    last_synced_at INTEGER,
    dirty INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_type, entity_id)
);

-- 写一次初始 schema 版本到 meta_kv
INSERT OR IGNORE INTO meta_kv (key, value, updated_at)
VALUES ('schema_version', '1', strftime('%s', 'now') * 1000);

INSERT OR IGNORE INTO meta_kv (key, value, updated_at)
VALUES ('m2_initialized', 'true', strftime('%s', 'now') * 1000);
