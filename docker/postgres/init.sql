CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS cdr (
  id BIGSERIAL PRIMARY KEY,
  source_uid TEXT NOT NULL UNIQUE,
  calldate TIMESTAMP NOT NULL,
  src TEXT NOT NULL DEFAULT '',
  dst TEXT NOT NULL DEFAULT '',
  dcontext TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT '',
  dstchannel TEXT NOT NULL DEFAULT '',
  disposition TEXT NOT NULL DEFAULT '',
  duration INTEGER NOT NULL DEFAULT 0,
  billsec INTEGER NOT NULL DEFAULT 0,
  lastapp TEXT NOT NULL DEFAULT '',
  lastdata TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_cdr_calldate ON cdr (calldate);
CREATE INDEX IF NOT EXISTS idx_cdr_src_dst ON cdr (src, dst);

CREATE TABLE IF NOT EXISTS agents (
  id BIGSERIAL PRIMARY KEY,
  extension TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  department TEXT NOT NULL DEFAULT '',
  outbound_cid TEXT NOT NULL DEFAULT '',
  voicemail TEXT NOT NULL DEFAULT '',
  ringtimer INTEGER,
  noanswer TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  source_hash TEXT NOT NULL DEFAULT '',
  last_seen_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_extension ON agents (extension);

CREATE TABLE IF NOT EXISTS sync_state (
  sync_key TEXT PRIMARY KEY,
  synced_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portal_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
  full_name TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_users_username ON portal_users (lower(username));
