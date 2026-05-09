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
