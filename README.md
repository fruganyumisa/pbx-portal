# PBX Portal

A lightweight FreePBX/Asterisk call-center performance dashboard. The backend imports standard FreePBX CDR rows from the PBX host into the portal Postgres database, then the dashboard reads from that local portal store. The frontend is a Next.js dashboard. If Postgres is not configured, the backend can still run with demo data.

## What it tracks

- Total, answered, and missed calls per agent
- Answer rate, average talk time, average ring time
- Call register with timestamp, source, destination, status, duration, talk time, and ring time
- Calls received, calls placed, calls hung before answer, failed or busy calls
- Agent active time, talk time, idle time, occupancy, and pauses
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

Services:

- Postgres: `localhost:5432`
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
export QUEUE_LOG_PATH=/var/log/asterisk/queue_log
```

`POSTGRES_*` points to the portal Postgres database. `DATABASE_URL` can override those settings. `PBX_DB_*` points to the FreePBX MariaDB database that the sync process reads from.

Use a read-only MariaDB user for the PBX host. The app only needs `SELECT` access to `asteriskcdrdb.cdr`.

Example SQL on the PBX database server:

```sql
CREATE USER 'pbx_portal'@'%' IDENTIFIED BY 'strong-password';
GRANT SELECT ON asteriskcdrdb.cdr TO 'pbx_portal'@'%';
FLUSH PRIVILEGES;
```

## FreePBX data sources

This version avoids paid FreePBX modules by using standard Asterisk/FreePBX artifacts:

- PBX source: `asteriskcdrdb.cdr` on the FreePBX MariaDB host
- Portal store: `cdr` table in the bundled Postgres container
- Optional local file source: `/var/log/asterisk/queue_log` for queue membership, pause, unpause, connect, and remove events

For a production deployment, put the Flask app behind Nginx, enable authentication, and run it close to the PBX database or a read replica.
