import csv
import os
from datetime import datetime


class CdrRepository:
    def __init__(self, database_url=None):
        self.database_url = database_url
        if database_url:
            self.source_name = "portal Postgres database"
        else:
            self.source_name = "unconfigured portal database"

    @classmethod
    def from_env(cls):
        database_url = _database_url_from_env()
        if database_url:
            return cls(database_url=database_url)
        raise RuntimeError("DATABASE_URL or POSTGRES_* settings are required for portal storage")

    def fetch_calls(self, start, end, queue=None, agent=None):
        return self._fetch_postgres_calls(start=start, end=end, queue=queue, agent=agent)

    def _fetch_postgres_calls(self, start, end, queue=None, agent=None):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

        ensure_portal_schema(self.database_url)

        sql = """
            SELECT calldate, src, dst, dcontext, channel, dstchannel, disposition,
                   duration, billsec, lastapp, lastdata
            FROM cdr
            WHERE calldate >= %(start)s AND calldate <= %(end)s
        """
        params = {"start": start, "end": end}
        if agent:
            sql += """
                AND (
                    src = %(agent)s OR dst = %(agent)s OR
                    channel LIKE %(agent_like)s OR dstchannel LIKE %(agent_like)s
                )
            """
            params["agent"] = agent
            params["agent_like"] = f"%/{agent}-%"
        if queue:
            sql += " AND (lastdata ILIKE %(queue_like)s OR dcontext ILIKE %(queue_like)s)"
            params["queue_like"] = f"%{queue}%"
        sql += " ORDER BY calldate DESC LIMIT 50000"

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()

        return [_normalize_cdr(row) for row in rows]

    def fetch_recent_calls(self, start, end, queue=None, agent=None, limit=200):
        calls = self.fetch_calls(start=start, end=end, queue=queue, agent=agent)
        return [_call_register_row(call) for call in calls[:limit]]


class FreePbxCdrSource:
    def __init__(self, mysql_config=None):
        self.mysql_config = mysql_config

    @classmethod
    def from_env(cls):
        host = os.getenv("PBX_DB_HOST")
        user = os.getenv("PBX_DB_USER")
        password = os.getenv("PBX_DB_PASSWORD")
        database = os.getenv("PBX_DB_NAME", "asteriskcdrdb")
        port = int(os.getenv("PBX_DB_PORT", "3306"))
        if host and user:
            return cls(
                {
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                }
            )
        return cls()

    @property
    def configured(self):
        return bool(self.mysql_config)

    def fetch_calls(self, start, end):
        if not self.mysql_config:
            raise RuntimeError("FreePBX database settings are not configured")

        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("Install PyMySQL to connect to FreePBX: pip install PyMySQL") from exc

        sql = """
            SELECT calldate, src, dst, dcontext, channel, dstchannel, disposition,
                   duration, billsec, lastapp, lastdata
            FROM cdr
            WHERE calldate >= %s AND calldate <= %s
            ORDER BY calldate DESC
            LIMIT 50000
        """
        with pymysql.connect(
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=30,
            **self.mysql_config,
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (start, end))
                rows = cursor.fetchall()

        calls = [_normalize_cdr(row) for row in rows]
        return calls


class PortalCdrStore:
    def __init__(self, database_url):
        self.database_url = database_url

    @classmethod
    def from_env(cls):
        database_url = _database_url_from_env()
        if not database_url:
            raise RuntimeError("DATABASE_URL or POSTGRES_* settings are required for portal storage")
        return cls(database_url)

    def upsert_calls(self, calls):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

        ensure_portal_schema(self.database_url)
        rows = [_portal_row(call) for call in calls]
        if not rows:
            return {"received": 0, "stored": 0}

        sql = """
            INSERT INTO cdr (
              source_uid, calldate, src, dst, dcontext, channel, dstchannel,
              disposition, duration, billsec, lastapp, lastdata
            )
            VALUES (
              %(source_uid)s, %(calldate)s, %(src)s, %(dst)s, %(dcontext)s,
              %(channel)s, %(dstchannel)s, %(disposition)s, %(duration)s,
              %(billsec)s, %(lastapp)s, %(lastdata)s
            )
            ON CONFLICT (source_uid) DO UPDATE SET
              calldate = EXCLUDED.calldate,
              src = EXCLUDED.src,
              dst = EXCLUDED.dst,
              dcontext = EXCLUDED.dcontext,
              channel = EXCLUDED.channel,
              dstchannel = EXCLUDED.dstchannel,
              disposition = EXCLUDED.disposition,
              duration = EXCLUDED.duration,
              billsec = EXCLUDED.billsec,
              lastapp = EXCLUDED.lastapp,
              lastdata = EXCLUDED.lastdata
        """
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.executemany(sql, rows)
            conn.commit()

        return {"received": len(rows), "stored": len(rows)}


def sync_freepbx_to_portal(start, end):
    source = FreePbxCdrSource.from_env()
    store = PortalCdrStore.from_env()
    calls = source.fetch_calls(start=start, end=end)
    result = store.upsert_calls(calls)
    result.update({"start": start.isoformat(), "end": end.isoformat()})
    return result


class QueueLogRepository:
    def __init__(self, path=None):
        self.path = path

    @classmethod
    def from_env(cls):
        return cls(os.getenv("QUEUE_LOG_PATH"))

    def fetch_events(self, start, end, queue=None, agent=None):
        if not self.path or not os.path.exists(self.path):
            return []

        events = []
        with open(self.path, newline="", encoding="utf-8", errors="ignore") as handle:
            reader = csv.reader(handle, delimiter="|")
            for row in reader:
                if len(row) < 5:
                    continue
                timestamp = _queue_timestamp(row[0])
                if not timestamp or timestamp < start or timestamp > end:
                    continue
                event = {
                    "timestamp": timestamp,
                    "queue": row[2],
                    "agent": row[3].replace("Local/", "").split("@")[0],
                    "event": row[4],
                }
                if queue and event["queue"] != queue:
                    continue
                if agent and event["agent"] != agent:
                    continue
                events.append(event)
        return events


def _normalize_cdr(row):
    calldate = row["calldate"]
    if isinstance(calldate, str):
        calldate = datetime.strptime(calldate, "%Y-%m-%d %H:%M:%S")

    src = str(row.get("src") or "")
    dst = str(row.get("dst") or "")
    channel = str(row.get("channel") or "")
    dstchannel = str(row.get("dstchannel") or "")
    disposition = str(row.get("disposition") or "")
    duration = int(row.get("duration") or 0)
    billsec = int(row.get("billsec") or 0)
    agent = _agent_from_channels(src, dst, channel, dstchannel)
    direction = "outbound" if agent == src else "inbound"

    return {
        "calldate": calldate,
        "agent": agent,
        "src": src,
        "dst": dst,
        "dcontext": str(row.get("dcontext") or ""),
        "channel": channel,
        "dstchannel": dstchannel,
        "disposition": disposition,
        "lastapp": str(row.get("lastapp") or ""),
        "lastdata": str(row.get("lastdata") or ""),
        "direction": direction,
        "answered": disposition.upper() == "ANSWERED" and billsec > 0,
        "duration": duration,
        "billsec": billsec,
        "ring_seconds": max(duration - billsec, 0),
        "queue": _queue_from_context(row),
    }


def _agent_from_channels(src, dst, channel, dstchannel):
    for value in (dstchannel, channel, dst, src):
        extension = _extension(value)
        if extension:
            return extension
    return "unassigned"


def _extension(value):
    value = str(value)
    if "/" in value:
        value = value.split("/", 1)[1]
    value = value.split("-", 1)[0].split("@", 1)[0]
    return value if value.isdigit() and 2 <= len(value) <= 6 else None


def _queue_from_context(row):
    for key in ("lastdata", "dcontext"):
        value = str(row.get(key) or "")
        if "queue" in value.lower():
            return value
    return None


def _queue_timestamp(value):
    try:
        return datetime.fromtimestamp(int(value))
    except (TypeError, ValueError, OSError):
        return None


def _portal_row(call):
    return {
        "source_uid": _source_uid(call),
        "calldate": call["calldate"],
        "src": call.get("src") or "",
        "dst": call.get("dst") or "",
        "dcontext": call.get("dcontext") or "",
        "channel": call.get("channel") or "",
        "dstchannel": call.get("dstchannel") or "",
        "disposition": call.get("disposition") or "",
        "duration": int(call.get("duration") or 0),
        "billsec": int(call.get("billsec") or 0),
        "lastapp": call.get("lastapp") or "",
        "lastdata": call.get("lastdata") or "",
    }


def _source_uid(call):
    parts = [
        call["calldate"].isoformat() if hasattr(call["calldate"], "isoformat") else str(call["calldate"]),
        call.get("src") or "",
        call.get("dst") or "",
        call.get("channel") or "",
        call.get("dstchannel") or "",
        str(call.get("duration") or 0),
        str(call.get("billsec") or 0),
    ]
    import hashlib

    return hashlib.md5("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()


def ensure_portal_schema(database_url):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

    statements = [
        """
        CREATE TABLE IF NOT EXISTS cdr (
          id BIGSERIAL PRIMARY KEY,
          source_uid TEXT,
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
        )
        """,
        "ALTER TABLE cdr ADD COLUMN IF NOT EXISTS source_uid TEXT",
        "UPDATE cdr SET source_uid = md5(calldate::TEXT || '|' || src || '|' || dst || '|' || channel || '|' || dstchannel || '|' || duration::TEXT || '|' || billsec::TEXT) WHERE source_uid IS NULL",
        "ALTER TABLE cdr ALTER COLUMN source_uid SET NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cdr_source_uid ON cdr (source_uid)",
        "CREATE INDEX IF NOT EXISTS idx_cdr_calldate ON cdr (calldate)",
        "CREATE INDEX IF NOT EXISTS idx_cdr_src_dst ON cdr (src, dst)",
    ]
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        conn.commit()


def _database_url_from_env():
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    if user and password and database:
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"
    return None


def _call_register_row(call):
    return {
        "time": call["calldate"].isoformat(),
        "source": call["src"],
        "destination": call["dst"],
        "agent": call["agent"],
        "direction": call["direction"],
        "status": "Answered" if call["answered"] else call["disposition"].title() or "Unanswered",
        "duration_seconds": call["duration"],
        "talk_seconds": call["billsec"],
        "ring_seconds": call["ring_seconds"],
        "queue": call.get("queue"),
        "channel": call["channel"],
    }
