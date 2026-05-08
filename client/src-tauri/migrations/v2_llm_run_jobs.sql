-- M3 Phase B v2: LLM 任务队列持久化（断网重启续跑）
-- 与 client/src/data/llm/concurrent_queue.ts 配套使用
-- forward-only：本 plugin 实际不跑 down migration（tauri-plugin-sql v2 issue #1346）
CREATE TABLE IF NOT EXISTS llm_run_jobs (
  job_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  doc_id TEXT,
  agent_kind TEXT NOT NULL,    -- 'scoring' | 'summary' | 'graph' | 'memory' | ...
  prompt_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
  result_json TEXT,
  error_message TEXT,
  retried_count INTEGER NOT NULL DEFAULT 0,
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_run_jobs_run_status ON llm_run_jobs(run_id, status);
CREATE INDEX IF NOT EXISTS idx_llm_run_jobs_status_kind ON llm_run_jobs(status, agent_kind);

-- 标记 v2 已应用（与 v1 保持一致）
INSERT OR REPLACE INTO meta_kv (key, value, updated_at)
VALUES ('schema_version', '2', strftime('%s', 'now') * 1000);
