CREATE TABLE IF NOT EXISTS threads (
  id           TEXT PRIMARY KEY,
  tenant       JSONB NOT NULL DEFAULT '{}',
  metadata     JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS threads_tenant_gin ON threads USING GIN (tenant jsonb_path_ops);
CREATE INDEX IF NOT EXISTS threads_created_at ON threads (created_at DESC, id);

CREATE TABLE IF NOT EXISTS runs (
  id                TEXT PRIMARY KEY,
  thread_id         TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  assistant         JSONB NOT NULL,
  triggered_by      JSONB NOT NULL,
  status            TEXT NOT NULL,
  error             JSONB,
  idempotency_key   TEXT,
  metadata          JSONB NOT NULL DEFAULT '{}',
  started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at      TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS runs_idempotency
  ON runs (thread_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS runs_active_per_assistant
  ON runs (thread_id, (assistant->>'id'))
  WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS runs_thread ON runs (thread_id, started_at DESC);

CREATE TABLE IF NOT EXISTS events (
  id           TEXT PRIMARY KEY,
  thread_id    TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  run_id       TEXT REFERENCES runs(id) ON DELETE SET NULL,
  type         TEXT NOT NULL,
  author       JSONB NOT NULL,
  payload      JSONB NOT NULL,
  metadata     JSONB NOT NULL DEFAULT '{}',
  client_id    TEXT,
  recipients   JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE events ADD COLUMN IF NOT EXISTS recipients JSONB;
CREATE INDEX IF NOT EXISTS events_thread_time ON events (thread_id, created_at, id);
CREATE INDEX IF NOT EXISTS events_thread_type ON events (thread_id, type);
CREATE INDEX IF NOT EXISTS events_run ON events (run_id) WHERE run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS thread_members (
  thread_id     TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  identity_id   TEXT NOT NULL,
  identity      JSONB NOT NULL,
  role          TEXT NOT NULL DEFAULT 'member',
  added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  added_by      JSONB NOT NULL,
  PRIMARY KEY (thread_id, identity_id)
);
CREATE INDEX IF NOT EXISTS members_identity ON thread_members (identity_id);
