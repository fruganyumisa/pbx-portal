# PBX Portal

A lightweight FreePBX/Asterisk call-center performance dashboard. The backend imports standard FreePBX CDR rows from the PBX host into the portal Postgres database, then the dashboard reads from that local portal store. The frontend is a Next.js dashboard. If Postgres is not configured, the backend can still run with demo data.

## What it tracks

- Total, answered, and missed calls per agent
- Answer rate, average talk time, average ring time
- Call register with timestamp, source, destination, status, duration, talk time, and ring time
- Calls received, calls placed, calls hung before answer, failed or busy calls
- Agent active time, talk time, idle time, occupancy, and pauses
- Synced agent directory from FreePBX `users`
- Top call sources and destinations
- Call duration distribution
- Inbound vs outbound call mix
- Estimated occupancy
- Efficiency score for ranking agents
- Daily call volume trend

The score is intentionally transparent:

```text
score = answer_rate * 0.55 + occupancy * 0.5 - ring_time_penalty
```

If queue logs are available, occupancy uses queue availability time. Without queue logs, it estimates availability from the first and last observed call in the selected period.

## Run locally

### Docker Compose

Run the full stack with three containers:

```bash
cp .env.example .env
docker compose up --build
```

For background mode:

```bash
docker compose up --build -d
```

Services:

- Postgres: internal Docker network only (not published to host)
- Flask API: `http://localhost:5000`
- Next.js frontend: `http://localhost:3000`

The Postgres container creates an empty `cdr` table on first startup. Compose reads Postgres settings from `.env`:

```text
POSTGRES_DB=pbx_portal
POSTGRES_USER=pbx_portal
POSTGRES_PASSWORD=pbx_portal
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Inside Docker, the backend uses `POSTGRES_HOST=db` and builds the portal database connection from the same Postgres credentials. You can still set `DATABASE_URL` explicitly if you need to override that behavior.

### Production tuning with environment variables

Backend runs with Gunicorn in Compose. These variables are available in `.env.example` for production tuning:

```text
BACKEND_BIND_HOST=127.0.0.1
BACKEND_EXPOSE_PORT=5000
FRONTEND_BIND_HOST=127.0.0.1
FRONTEND_EXPOSE_PORT=3000

GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=120
GUNICORN_GRACEFUL_TIMEOUT=30
GUNICORN_KEEPALIVE=5
GUNICORN_MAX_REQUESTS=1000
GUNICORN_MAX_REQUESTS_JITTER=100

SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=Lax
SESSION_COOKIE_SECURE=false
TRUST_PROXY=false
APP_LOG_LEVEL=INFO
```

For TLS-terminated deployments behind Nginx or a load balancer, set:

```text
SESSION_COOKIE_SECURE=true
TRUST_PROXY=true
```

To follow backend sync activity in real time:

```bash
docker compose logs -f backend
```

Filter only sync-related lines:

```bash
docker compose logs -f backend | grep -Ei 'sync started|sync completed|sync failed|sync rejected|background sync'
```

The portal does not seed demo CDR data. The dashboard remains empty until real PBX records are imported.

Postgres is the portal database, not the PBX database. To import live PBX calls, provide FreePBX read-only MariaDB settings to Compose:

```bash
PBX_DB_HOST=freepbx-host-or-ip \
PBX_DB_USER=readonly_user \
PBX_DB_PASSWORD='your-password' \
docker compose up --build -d
```

Then click `Sync PBX` in the dashboard or call:

```bash
curl -X POST 'http://localhost:5000/api/sync?days=1'
```

Sync imports both CDR rows and agent records. The portal stores all imported history in Postgres, so old calls remain available for filtering after later syncs.

CDR import is chunked by time window and query limit to handle large datasets without single long-running PBX queries.

CDR sync is incremental. The portal stores the last successful CDR sync time in `sync_state`; the next sync pulls only calls from that timestamp up to the current timestamp. On the first sync, provide an explicit `start` or let the default one-day bootstrap run:

```bash
curl -X POST 'http://localhost:5000/api/sync?start=2026-05-01T00:00:00&end=2026-05-11T18:30:00'
```

Agent records are read from the FreePBX configuration database `users` table, normally `asterisk.users`, and saved into the portal Postgres `agents` table. Repeated syncs are idempotent: new agents are inserted, changed agent details are updated, and unchanged synced agents remain stored in Postgres.

The call register is paginated from Postgres:

```bash
curl 'http://localhost:5000/api/calls?start=2026-05-11T08:00:00&end=2026-05-11T18:30:00&page=1&per_page=50'
```

To clear imported portal data and rebuild the database volume:

```bash
docker compose down -v
docker compose up --build
```

### Manual development

Start the Flask API:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app app run --host 0.0.0.0 --port 5000
```

In another terminal, start the Next.js frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

The Next app proxies `/api/*` to the Flask API. To use a different backend URL:

```bash
PBX_API_URL=http://your-api-host:5000 npm run dev
```

## Connect to FreePBX

Create environment variables from `.env.example`:

```bash
export POSTGRES_DB=pbx_portal
export POSTGRES_USER=pbx_portal
export POSTGRES_PASSWORD=pbx_portal
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export PBX_DB_HOST=freepbx-host-or-ip
export PBX_DB_USER=readonly_user
export PBX_DB_PASSWORD='your-password'
export PBX_DB_NAME=asteriskcdrdb
export PBX_CONFIG_DB_NAME=asterisk
export PBX_DB_CONNECT_TIMEOUT_SECONDS=10
export PBX_DB_READ_TIMEOUT_SECONDS=180
export PBX_DB_WRITE_TIMEOUT_SECONDS=30
export PBX_DB_RETRY_ATTEMPTS=3
export PBX_DB_RETRY_BASE_DELAY_SECONDS=2
export PBX_SYNC_QUERY_LIMIT=5000
export PBX_SYNC_WINDOW_MINUTES=60
export PBX_SYNC_MIN_WINDOW_SECONDS=60
export QUEUE_LOG_PATH=/var/log/asterisk/queue_log
```

`POSTGRES_*` points to the portal Postgres database. `DATABASE_URL` can override those settings. `PBX_DB_*` points to the FreePBX CDR database, and `PBX_CONFIG_DB_NAME` points to the FreePBX configuration database containing `users`.

Use a read-only MariaDB user for the PBX host. The app needs `SELECT` access to `asteriskcdrdb.cdr` and `asterisk.users`.

Example SQL on the PBX database server:

```sql
CREATE USER 'pbx_portal'@'%' IDENTIFIED BY 'strong-password';
GRANT SELECT ON asteriskcdrdb.cdr TO 'pbx_portal'@'%';
GRANT SELECT ON asterisk.users TO 'pbx_portal'@'%';
FLUSH PRIVILEGES;
```

## FreePBX data sources

This version avoids paid FreePBX modules by using standard Asterisk/FreePBX artifacts:

- PBX source: `asteriskcdrdb.cdr` on the FreePBX MariaDB host
- Portal store: `cdr` table in the bundled Postgres container
- Optional local file source: `/var/log/asterisk/queue_log` for queue membership, pause, unpause, connect, and remove events

For production, place the frontend/backend behind a reverse proxy (Nginx/Traefik), keep Postgres port bound to localhost or private network only, and run close to the PBX database or a read replica.
