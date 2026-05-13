# PBX Portal Sync Configuration Guide

This document explains the configuration options for the improved FreePBX sync system with connection pooling, rate limiting, and adaptive chunking.

## Overview of Improvements

The sync system has been enhanced to handle:
- **Connection pooling** - Reuse MySQL connections to reduce overhead
- **Rate limiting** - Throttle queries to avoid overwhelming the database
- **Adaptive chunking** - Automatically subdivide large time windows
- **Better timeouts** - Configurable timeouts with exponential backoff
- **Reduced defaults** - Safer defaults that prevent timeouts

## Environment Variables

### Connection Pool Configuration

```
PBX_DB_POOL_SIZE=5
```
- Pool size for MySQL connections (default: 5, minimum: 2)
- Increase if you have many concurrent sync operations
- Decrease to reduce memory usage

```
PBX_DB_CONNECT_TIMEOUT_SECONDS=15
```
- Timeout for establishing MySQL connections (default: 15 seconds)
- Increased from 10s to give more time for connection establishment
- Reduce if connections fail quickly and you want faster error reporting

### Query and Data Limits

```
PBX_SYNC_QUERY_LIMIT=1000
```
- Maximum rows per database query (default: 1000, was 5000)
- **Reduced to prevent timeouts** - Smaller batches are more reliable
- Minimum: 100 rows
- Increase only if sync is too slow and timeouts are not occurring

```
PBX_SYNC_MAX_ROWS=50000
```
- Hard cap on total rows that can be fetched per time window (default: 50000)
- If a window exceeds this, it will be subdivided
- Minimum: 1000 rows

```
PBX_SYNC_WINDOW_MINUTES=30
```
- Initial time window for CDR queries (default: 30 minutes, was 60)
- **Reduced to prevent timeouts** - Smaller windows = fewer rows per query
- If a window has too many rows, it's automatically subdivided
- Minimum: 1 minute

```
PBX_SYNC_MIN_WINDOW_SECONDS=60
```
- Smallest time window before pagination (default: 60 seconds)
- Windows smaller than this will be paginated instead of subdivided
- Minimum: 1 second

### Rate Limiting

```
PBX_SYNC_RATE_LIMIT_MS=100
```
- Throttle between batch queries (default: 100ms)
- Set to 0 to disable rate limiting (not recommended)
- Increase to 200-500ms to reduce database load
- This helps prevent connection pool exhaustion

### Retry Configuration

```
PBX_DB_RETRY_ATTEMPTS=3
```
- Number of retry attempts on failure (default: 3)
- Minimum: 1

```
PBX_DB_RETRY_BASE_DELAY_SECONDS=1.0
```
- Base delay for exponential backoff (default: 1.0 second, was 2.0)
- **Reduced for faster recovery** - Combined with connection pooling
- Each retry uses: base_delay * 2^(attempt-1) + random_jitter

```
PBX_DB_RETRY_MAX_DELAY_SECONDS=30.0
```
- Maximum delay between retries (default: 30 seconds)
- Prevents excessively long waits
- Increase if you need slower backoff for degraded database

### Auto-Sync Configuration

```
AUTO_SYNC_ENABLED=true
```
- Enable/disable automatic background sync (default: true)

```
SYNC_INTERVAL_SECONDS=600
```
- How often to run automatic sync (default: 600 seconds = 10 minutes)
- Reduce for more frequent syncs
- Increase to reduce database load

```
SYNC_INITIAL_DELAY_SECONDS=20
```
- Delay before first auto-sync starts on app startup (default: 20 seconds)

```
INITIAL_SYNC_DAYS=1
```
- Days to sync if no previous sync state exists (default: 1 day)

## Recommended Configurations

### For Small Deployments (< 50 CDRs/min)

```bash
PBX_SYNC_QUERY_LIMIT=1000
PBX_SYNC_WINDOW_MINUTES=30
PBX_SYNC_RATE_LIMIT_MS=100
PBX_DB_POOL_SIZE=3
SYNC_INTERVAL_SECONDS=600
```

### For Medium Deployments (50-500 CDRs/min)

```bash
PBX_SYNC_QUERY_LIMIT=2000
PBX_SYNC_WINDOW_MINUTES=20
PBX_SYNC_RATE_LIMIT_MS=200
PBX_DB_POOL_SIZE=5
SYNC_INTERVAL_SECONDS=300
```

### For High-Volume Deployments (> 500 CDRs/min)

```bash
PBX_SYNC_QUERY_LIMIT=3000
PBX_SYNC_WINDOW_MINUTES=15
PBX_SYNC_RATE_LIMIT_MS=300
PBX_DB_POOL_SIZE=8
SYNC_INTERVAL_SECONDS=180
```

### For Database Under Heavy Load

```bash
PBX_SYNC_QUERY_LIMIT=500
PBX_SYNC_WINDOW_MINUTES=10
PBX_SYNC_RATE_LIMIT_MS=500
PBX_DB_POOL_SIZE=2
SYNC_INTERVAL_SECONDS=900
```

## Troubleshooting

### Timeouts Still Occurring?

1. **Reduce query limits:**
   ```bash
   PBX_SYNC_QUERY_LIMIT=500
   PBX_SYNC_WINDOW_MINUTES=10
   ```

2. **Increase pool size:**
   ```bash
   PBX_DB_POOL_SIZE=8
   ```

3. **Add rate limiting:**
   ```bash
   PBX_SYNC_RATE_LIMIT_MS=500
   ```

### Sync Too Slow?

1. **Increase query limits** (if no timeouts):
   ```bash
   PBX_SYNC_QUERY_LIMIT=3000
   PBX_SYNC_WINDOW_MINUTES=45
   ```

2. **Reduce rate limiting:**
   ```bash
   PBX_SYNC_RATE_LIMIT_MS=50
   ```

3. **Increase sync frequency:**
   ```bash
   SYNC_INTERVAL_SECONDS=300
   ```

### High Database CPU Usage?

1. **Reduce query limits:**
   ```bash
   PBX_SYNC_QUERY_LIMIT=1000
   ```

2. **Increase rate limiting:**
   ```bash
   PBX_SYNC_RATE_LIMIT_MS=500
   ```

3. **Reduce sync frequency:**
   ```bash
   SYNC_INTERVAL_SECONDS=1200
   ```

### Connection Pool Errors?

If you see "Could not acquire MySQL connection from pool":
- Increase pool size: `PBX_DB_POOL_SIZE=10`
- Increase connection timeout: `PBX_DB_CONNECT_TIMEOUT_SECONDS=30`
- Reduce rate limiting: `PBX_SYNC_RATE_LIMIT_MS=200`

## Monitoring

Watch the logs for:
- "Background sync failed" - indicates a sync error
- "Large dataset...may cause timeouts" - time window has too many rows
- Database connection errors - may indicate pool exhaustion

## Migration Notes

### From Old Configuration

The old PyMySQL-based implementation has been replaced with mysql-connector-python for better connection pooling:

**Old environment variables (no longer used):**
- `PBX_DB_READ_TIMEOUT_SECONDS` - Not directly supported by mysql-connector
- `PBX_DB_WRITE_TIMEOUT_SECONDS` - Not directly supported by mysql-connector

**Old defaults that have changed:**
- `PBX_SYNC_QUERY_LIMIT`: 5000 → 1000
- `PBX_SYNC_WINDOW_MINUTES`: 60 → 30
- `PBX_DB_CONNECT_TIMEOUT_SECONDS`: 10 → 15
- `PBX_DB_RETRY_BASE_DELAY_SECONDS`: 2.0 → 1.0

If you have custom configurations, you may need to adjust them.
