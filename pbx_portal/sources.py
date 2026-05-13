import csv
import hashlib
import os
import time
import threading
from collections import deque
from datetime import datetime, timedelta


# Global connection pools for FreePBX MySQL databases (one per database)
_mysql_pools = {}  # Dict of database -> pool
_mysql_pools_lock = threading.Lock()


class MySQLConnectionPool:
    """Simple connection pool for FreePBX MySQL connections."""
    def __init__(self, config, pool_size=5, pool_name="freepbx_pool"):
        self.config = config
        self.pool_size = pool_size
        self.pool_name = pool_name
        self.available_connections = deque(maxlen=pool_size)
        self.all_connections = []
        self.lock = threading.Lock()
        self._initialize_pool()

    def _initialize_pool(self):
        """Create initial connections in the pool."""
        try:
            import mysql.connector
        except ImportError:
            raise RuntimeError("Install mysql-connector-python: pip install mysql-connector-python")
        
        for _ in range(self.pool_size):
            tries = 3
            while tries > 0:
                try:
                    conn = mysql.connector.connect(**self.config)
                    self.available_connections.append(conn)
                    self.all_connections.append(conn)
                    break
                except Exception:
                    tries -= 1
                    if tries == 0:
                        raise

    def get_connection(self, timeout=10):
        """Get a connection from the pool with timeout."""
        start_time = time.time()
        while True:
            with self.lock:
                if self.available_connections:
                    return self.available_connections.popleft()
            
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise RuntimeError(f"Could not acquire MySQL connection from pool within {timeout}s")
            time.sleep(0.1)

    def return_connection(self, conn):
        """Return a connection to the pool."""
        if conn:
            try:
                with self.lock:
                    self.available_connections.append(conn)
            except Exception:
                # Pool is full, close the connection
                try:
                    conn.close()
                except Exception:
                    pass

    def close_all(self):
        """Close all connections in the pool."""
        with self.lock:
            for conn in self.all_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self.available_connections.clear()
            self.all_connections.clear()


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

    def fetch_call_page(self, start, end, queue=None, agent=None, source=None, direction=None, status=None, page=1, per_page=50):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

        ensure_portal_schema(self.database_url)
        page = max(int(page or 1), 1)
        per_page = min(max(int(per_page or 50), 1), 200)
        where, params = _cdr_filters(start=start, end=end, queue=queue, agent=agent)
        data_sql = f"""
            SELECT calldate, src, dst, dcontext, channel, dstchannel, disposition,
                   duration, billsec, lastapp, lastdata
            FROM cdr
            WHERE {where}
            ORDER BY calldate DESC
            LIMIT 100000
        """
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(data_sql, params)
                calls = [_normalize_cdr(row) for row in cursor.fetchall()]

        call_rows = [_call_register_row(call) for call in calls]
        filtered = _filter_call_rows(call_rows, source=source, direction=direction, status=status)
        total = len(filtered)
        offset = (page - 1) * per_page
        paged = filtered[offset: offset + per_page]

        return {
            "calls": paged,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page if total else 0,
            },
        }

    def fetch_agents(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

        ensure_portal_schema(self.database_url)
        sql = """
            SELECT extension, name, email, department, outbound_cid, voicemail,
                   ringtimer, noanswer, enabled, last_seen_at
            FROM agents
            ORDER BY extension
        """
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                return [dict(row) for row in cursor.fetchall()]


class FreePbxCdrSource:
    def __init__(self, mysql_config=None):
        self.mysql_config = mysql_config

    @classmethod
    def from_env(cls):
        config = _pbx_mysql_config(os.getenv("PBX_DB_NAME", "asteriskcdrdb"))
        if config:
            return cls(config)
        return cls()

    @property
    def configured(self):
        return bool(self.mysql_config)

    def fetch_calls(self, start, end):
        calls = []
        for chunk in self.iter_calls_chunked(start=start, end=end):
            calls.extend(chunk)
        return calls

    def iter_calls_chunked(self, start, end):
        if not self.mysql_config:
            raise RuntimeError("FreePBX database settings are not configured")
        if start >= end:
            return

        # Configurable limits with reasonable defaults
        limit = max(_env_int("PBX_SYNC_QUERY_LIMIT", 1000), 100)  # Reduced from 5000
        max_rows = max(_env_int("PBX_SYNC_MAX_ROWS", 50000), 1000)  # Hard cap on total rows per window
        window_minutes = max(_env_int("PBX_SYNC_WINDOW_MINUTES", 30), 1)  # Reduced from 60
        min_window_seconds = max(_env_int("PBX_SYNC_MIN_WINDOW_SECONDS", 60), 1)
        rate_limit_ms = max(_env_int("PBX_SYNC_RATE_LIMIT_MS", 100), 0)  # Throttle between queries
        end_exclusive = end + timedelta(seconds=1)

        windows = deque()
        cursor = start
        while cursor < end_exclusive:
            next_cursor = min(cursor + timedelta(minutes=window_minutes), end_exclusive)
            windows.append((cursor, next_cursor))
            cursor = next_cursor

        while windows:
            window_start, window_end = windows.popleft()
            probe_rows = self._fetch_calls_window_rows(
                start=window_start,
                end_exclusive=window_end,
                limit=limit + 1,
                offset=0,
            )
            
            # If within limit, yield all rows
            if len(probe_rows) <= limit:
                if probe_rows:
                    yield [_normalize_cdr(row) for row in probe_rows]
                    if rate_limit_ms > 0:
                        time.sleep(rate_limit_ms / 1000.0)
                continue

            # Check total rows to prevent overwhelming the database
            if len(probe_rows) > max_rows:
                # Subdivide the window to reduce row count
                if (window_end - window_start).total_seconds() > min_window_seconds:
                    midpoint = window_start + ((window_end - window_start) / 2)
                    if window_start < midpoint < window_end:
                        windows.appendleft((midpoint, window_end))
                        windows.appendleft((window_start, midpoint))
                        continue
                else:
                    # Window too small to subdivide, paginate even though it's large
                    import warnings
                    warnings.warn(
                        f"Large dataset ({len(probe_rows)} rows) in small window "
                        f"[{window_start} to {window_end}]. May cause timeouts.",
                        RuntimeWarning
                    )

            # Paginate through results
            offset = 0
            while True:
                page_rows = self._fetch_calls_window_rows(
                    start=window_start,
                    end_exclusive=window_end,
                    limit=limit,
                    offset=offset,
                )
                if not page_rows:
                    break
                yield [_normalize_cdr(row) for row in page_rows]
                if rate_limit_ms > 0:
                    time.sleep(rate_limit_ms / 1000.0)
                if len(page_rows) < limit:
                    break
                offset += limit

    def _fetch_calls_window_rows(self, start, end_exclusive, limit, offset):
        sql = """
            SELECT calldate, src, dst, dcontext, channel, dstchannel, disposition,
                   duration, billsec, lastapp, lastdata
            FROM cdr
            WHERE calldate >= %s AND calldate < %s
            ORDER BY calldate ASC, src ASC, dst ASC, channel ASC, dstchannel ASC,
                     disposition ASC, duration ASC, billsec ASC
            LIMIT %s OFFSET %s
        """

        def _read():
            pool = _get_mysql_pool(self.mysql_config)
            conn = pool.get_connection(timeout=15)
            try:
                cursor = conn.cursor(dictionary=True)
                try:
                    cursor.execute(sql, (start, end_exclusive, int(limit), int(offset)))
                    return cursor.fetchall()
                finally:
                    cursor.close()
            finally:
                pool.return_connection(conn)

        return _with_pbx_retry("CDR fetch", _read)


class FreePbxAgentSource:
    def __init__(self, mysql_config=None):
        self.mysql_config = mysql_config

    @classmethod
    def from_env(cls):
        config = _pbx_mysql_config(os.getenv("PBX_CONFIG_DB_NAME", "asterisk"))
        if config:
            return cls(config)
        return cls()

    @property
    def configured(self):
        return bool(self.mysql_config)

    def fetch_agents(self):
        if not self.mysql_config:
            raise RuntimeError("FreePBX database settings are not configured")

        sql = """
            SELECT extension, name, voicemail, ringtimer, noanswer, outboundcid
            FROM users
            ORDER BY extension
        """
        def _read():
            pool = _get_mysql_pool(self.mysql_config)
            conn = pool.get_connection(timeout=15)
            try:
                cursor = conn.cursor(dictionary=True)
                try:
                    cursor.execute(sql)
                    return cursor.fetchall()
                finally:
                    cursor.close()
            finally:
                pool.return_connection(conn)

        rows = _with_pbx_retry("agent fetch", _read)

        return [_normalize_agent(row) for row in rows if _extension(row.get("extension"))]


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

    def upsert_agents(self, agents):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

        ensure_portal_schema(self.database_url)
        rows = [_agent_row(agent) for agent in agents]
        if not rows:
            return {"received": 0, "inserted": 0, "updated": 0, "unchanged": 0}

        sql = """
            INSERT INTO agents (
              extension, name, email, department, outbound_cid, voicemail,
              ringtimer, noanswer, enabled, source_hash, last_seen_at
            )
            VALUES (
              %(extension)s, %(name)s, %(email)s, %(department)s, %(outbound_cid)s,
              %(voicemail)s, %(ringtimer)s, %(noanswer)s, %(enabled)s,
              %(source_hash)s, NOW()
            )
            ON CONFLICT (extension) DO UPDATE SET
              name = EXCLUDED.name,
              email = EXCLUDED.email,
              department = EXCLUDED.department,
              outbound_cid = EXCLUDED.outbound_cid,
              voicemail = EXCLUDED.voicemail,
              ringtimer = EXCLUDED.ringtimer,
              noanswer = EXCLUDED.noanswer,
              enabled = EXCLUDED.enabled,
              source_hash = EXCLUDED.source_hash,
              last_seen_at = NOW(),
              updated_at = NOW()
            WHERE agents.source_hash IS DISTINCT FROM EXCLUDED.source_hash
            RETURNING (xmax = 0) AS inserted
        """
        inserted = 0
        updated = 0
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                for row in rows:
                    cursor.execute(sql, row)
                    result = cursor.fetchone()
                    if not result:
                        continue
                    if result[0]:
                        inserted += 1
                    else:
                        updated += 1
            conn.commit()

        changed = inserted + updated
        return {
            "received": len(rows),
            "inserted": inserted,
            "updated": updated,
            "unchanged": len(rows) - changed,
        }

    def get_sync_timestamp(self, key):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

        ensure_portal_schema(self.database_url)
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT synced_at FROM sync_state WHERE sync_key = %s", (key,))
                row = cursor.fetchone()
                return row[0] if row else None

    def set_sync_timestamp(self, key, synced_at):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

        ensure_portal_schema(self.database_url)
        sql = """
            INSERT INTO sync_state (sync_key, synced_at, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (sync_key) DO UPDATE SET
              synced_at = EXCLUDED.synced_at,
              updated_at = NOW()
        """
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (key, synced_at))
            conn.commit()


def sync_freepbx_to_portal(start=None, end=None, fallback_start=None):
    cdr_source = FreePbxCdrSource.from_env()
    agent_source = FreePbxAgentSource.from_env()
    store = PortalCdrStore.from_env()
    end = end or datetime.utcnow()
    last_cdr_sync = store.get_sync_timestamp("cdr")
    last_agent_sync = store.get_sync_timestamp("agents")
    cdr_start = start or last_cdr_sync or fallback_start
    if not cdr_start:
        raise RuntimeError("No previous CDR sync exists. Provide start or days for the first sync.")

    warnings = []
    agent_result = {
        "received": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "synced": False,
    }
    try:
        agents = agent_source.fetch_agents()
        agent_result = {
            **store.upsert_agents(agents),
            "synced": True,
        }
    except Exception as exc:
        warnings.append(str(exc))
        agent_result = {
            **agent_result,
            "error": str(exc),
        }

    call_totals = {"received": 0, "stored": 0}
    call_chunks = 0
    for calls_chunk in cdr_source.iter_calls_chunked(start=cdr_start, end=end):
        chunk_result = store.upsert_calls(calls_chunk)
        call_totals["received"] += chunk_result["received"]
        call_totals["stored"] += chunk_result["stored"]
        call_chunks += 1

    store.set_sync_timestamp("cdr", end)
    if agent_result["synced"]:
        store.set_sync_timestamp("agents", end)
    return {
        "start": cdr_start.isoformat(),
        "end": end.isoformat(),
        "previous_cdr_sync": last_cdr_sync.isoformat() if last_cdr_sync else None,
        "previous_agent_sync": last_agent_sync.isoformat() if last_agent_sync else None,
        "agents": agent_result,
        "calls": {
            **call_totals,
            "chunks": call_chunks,
        },
        "partial": bool(warnings),
        "warnings": warnings,
    }


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
    direction = _direction(agent=agent, src=src, dst=dst, channel=channel, dstchannel=dstchannel)
    source_display = agent if direction == "outbound" and agent != "unassigned" else src

    return {
        "calldate": calldate,
        "agent": agent,
        "src": src,
        "dst": dst,
        "source_display": source_display,
        "destination_display": dst,
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


def _normalize_agent(row):
    extension = str(row.get("extension") or "").strip()
    name = str(row.get("name") or "").strip()
    return {
        "extension": extension,
        "name": name or extension,
        "email": str(row.get("email") or "").strip(),
        "department": str(row.get("department") or "").strip(),
        "outbound_cid": str(row.get("outboundcid") or "").strip(),
        "voicemail": str(row.get("voicemail") or "").strip(),
        "ringtimer": _nullable_int(row.get("ringtimer")),
        "noanswer": str(row.get("noanswer") or "").strip(),
        "enabled": True,
    }


def _agent_from_channels(src, dst, channel, dstchannel):
    for value in (dstchannel, channel, dst, src):
        extension = _extension(value)
        if extension:
            return extension
    return "unassigned"


def _cdr_filters(start, end, queue=None, agent=None):
    clauses = ["calldate >= %(start)s", "calldate <= %(end)s"]
    params = {"start": start, "end": end}
    if agent:
        clauses.append(
            """
            (
                src = %(agent)s OR dst = %(agent)s OR
                channel LIKE %(agent_like)s OR dstchannel LIKE %(agent_like)s
            )
            """
        )
        params["agent"] = agent
        params["agent_like"] = f"%/{agent}-%"
    if queue:
        clauses.append("(lastdata ILIKE %(queue_like)s OR dcontext ILIKE %(queue_like)s)")
        params["queue_like"] = f"%{queue}%"
    return " AND ".join(clauses), params


def _direction(agent, src, dst, channel, dstchannel):
    if agent == "unassigned":
        return "inbound"

    origin_extension = _extension(channel)
    destination_extension = _extension(dstchannel)
    dialed_extension = _extension(dst)

    if origin_extension == agent and destination_extension != agent:
        return "outbound"
    if src == agent and dialed_extension != agent:
        return "outbound"
    return "inbound"


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


def _agent_row(agent):
    source_hash = _agent_source_hash(agent)
    return {
        "extension": agent["extension"],
        "name": agent.get("name") or agent["extension"],
        "email": agent.get("email") or "",
        "department": agent.get("department") or "",
        "outbound_cid": agent.get("outbound_cid") or "",
        "voicemail": agent.get("voicemail") or "",
        "ringtimer": agent.get("ringtimer"),
        "noanswer": agent.get("noanswer") or "",
        "enabled": bool(agent.get("enabled", True)),
        "source_hash": source_hash,
    }


def _agent_source_hash(agent):
    parts = [
        agent.get("extension") or "",
        agent.get("name") or "",
        agent.get("email") or "",
        agent.get("department") or "",
        agent.get("outbound_cid") or "",
        agent.get("voicemail") or "",
        str(agent.get("ringtimer") or ""),
        agent.get("noanswer") or "",
        str(bool(agent.get("enabled", True))),
    ]
    return hashlib.md5("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()


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
    return hashlib.md5("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()


def ensure_portal_schema(database_url):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg to connect to Postgres: pip install psycopg[binary]") from exc

    statements = [
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
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
        """
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
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_extension ON agents (extension)",
        """
        CREATE TABLE IF NOT EXISTS sync_state (
          sync_key TEXT PRIMARY KEY,
          synced_at TIMESTAMP NOT NULL,
          updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """
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
        )
        """,
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'portal_users'
                  AND column_name = 'id'
                  AND data_type <> 'uuid'
            ) THEN
                ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS id_uuid UUID;
                UPDATE portal_users SET id_uuid = gen_random_uuid() WHERE id_uuid IS NULL;
                ALTER TABLE portal_users ALTER COLUMN id_uuid SET NOT NULL;
                ALTER TABLE portal_users DROP CONSTRAINT IF EXISTS portal_users_pkey;
                ALTER TABLE portal_users ADD CONSTRAINT portal_users_pkey PRIMARY KEY (id_uuid);
                ALTER TABLE portal_users DROP COLUMN id;
                ALTER TABLE portal_users RENAME COLUMN id_uuid TO id;
                ALTER TABLE portal_users ALTER COLUMN id SET DEFAULT gen_random_uuid();
            END IF;
        END $$;
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_users_username ON portal_users (lower(username))",
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


def _get_mysql_pool(mysql_config):
    """Get or create a MySQL connection pool for the specific database."""
    global _mysql_pools
    
    # Use database name as the pool key
    database = mysql_config.get('database', 'default')
    
    if database in _mysql_pools and _mysql_pools[database] is not None:
        return _mysql_pools[database]
    
    with _mysql_pools_lock:
        # Double-check after acquiring lock
        if database in _mysql_pools and _mysql_pools[database] is not None:
            return _mysql_pools[database]
        
        pool_size = max(_env_int("PBX_DB_POOL_SIZE", 5), 2)
        enhanced_config = {**mysql_config, **_pbx_mysql_connect_kwargs()}
        pool = MySQLConnectionPool(enhanced_config, pool_size=pool_size, pool_name=f"pool_{database}")
        _mysql_pools[database] = pool
        return pool


def _pbx_mysql_connect_kwargs():
    """Get connection kwargs for mysql-connector-python."""
    return {
        "connect_timeout": _env_int("PBX_DB_CONNECT_TIMEOUT_SECONDS", 15),
        "get_warnings": False,
        "use_pure": True,  # Use pure Python implementation for better compatibility
        # Note: mysql-connector does not have read_timeout at the connection level,
        # but individual queries can have timeouts. Consider using connection.query_timeout
    }


def _pbx_mysql_config(database):
    host = os.getenv("PBX_DB_HOST")
    user = os.getenv("PBX_DB_USER")
    password = os.getenv("PBX_DB_PASSWORD")
    port = int(os.getenv("PBX_DB_PORT", "3306"))
    if not host or not user:
        return None
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
        "charset": "utf8mb4",
        "autocommit": True,
    }


def _with_pbx_retry(operation, fn):
    attempts = max(_env_int("PBX_DB_RETRY_ATTEMPTS", 3), 1)
    base_delay = max(_env_float("PBX_DB_RETRY_BASE_DELAY_SECONDS", 1.0), 0.0)
    max_delay = max(_env_float("PBX_DB_RETRY_MAX_DELAY_SECONDS", 30.0), base_delay)
    
    try:
        import mysql.connector
    except ImportError:
        raise RuntimeError("Install mysql-connector-python: pip install mysql-connector-python")

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (mysql.connector.Error, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            
            # Exponential backoff with jitter and cap
            sleep_for = base_delay * (2 ** (attempt - 1))
            sleep_for = min(sleep_for, max_delay)
            
            if sleep_for > 0:
                import random
                jitter = random.uniform(0, 0.1 * sleep_for)
                time.sleep(sleep_for + jitter)
    
    raise RuntimeError(f"PBX {operation} failed after {attempts} attempts: {last_error}")


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _nullable_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _call_register_row(call):
    return {
        "time": call["calldate"].isoformat(),
        "source": call.get("source_display") or call["src"],
        "raw_source": call["src"],
        "destination": call.get("destination_display") or call["dst"],
        "agent": call["agent"],
        "direction": call["direction"],
        "status": "Answered" if call["answered"] else call["disposition"].title() or "Unanswered",
        "duration_seconds": call["duration"],
        "talk_seconds": call["billsec"],
        "ring_seconds": call["ring_seconds"],
        "queue": call.get("queue"),
        "channel": call["channel"],
    }


def _filter_call_rows(rows, source=None, direction=None, status=None):
    filtered = rows

    if source:
        source_query = source.strip().lower()
        filtered = [
            row
            for row in filtered
            if source_query in str(row.get("source") or "").lower()
            or source_query in str(row.get("raw_source") or "").lower()
        ]

    if direction:
        direction_query = direction.strip().lower()
        if direction_query in {"inbound", "outbound"}:
            filtered = [row for row in filtered if str(row.get("direction") or "").lower() == direction_query]

    if status:
        status_query = status.strip().lower()
        filtered = [row for row in filtered if _normalize_status(row.get("status")) == status_query]

    return filtered


def _normalize_status(value):
    normalized = " ".join(str(value or "").strip().lower().split())
    if normalized in {"cancel", "canceled", "cancelled"}:
        return "canceled"
    if normalized in {"no answer", "noanswer"}:
        return "no answer"
    return normalized
