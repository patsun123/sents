# Operations Runbook

## Reset Database

Wipe all data and re-run schema initialization:

```bash
docker compose down -v && docker compose up --build
```

The `-v` flag removes all named volumes (postgres_data, redis_data, etc.). When PostgreSQL starts with an empty data directory, it automatically runs `database/init.sql` from the Docker entrypoint, recreating all roles, tables, and seed data.

Warning: This destroys all data including scraped posts, sentiment scores, and price history.

## Restart Individual Services

Restart a single service without rebuilding:

```bash
docker compose restart scraper
docker compose restart processor
docker compose restart pricing_engine
docker compose restart api
```

To rebuild and restart (picks up code changes):

```bash
docker compose up --build -d scraper
```

## View Logs

Follow logs for a specific service in real time:

```bash
docker compose logs -f scraper
docker compose logs -f processor
docker compose logs -f pricing_engine
docker compose logs -f api
```

View the last N lines:

```bash
docker compose logs --tail=100 processor
```

View logs for all services:

```bash
docker compose logs -f
```

Logs are stored as JSON files with a 10 MB max size and 5-file rotation (configured in docker-compose.yml).

## Check Service Health

Each Python service exposes a health endpoint:

```bash
# Scraper
curl http://localhost:8001/health

# Processor
curl http://localhost:8002/health

# Pricing Engine
curl http://localhost:8003/health

# Backend API
curl http://localhost:8000/api/v1/health
```

Check the overall status of all containers:

```bash
docker compose ps
```

Healthy containers show `(healthy)` in the status column. If a service is `(unhealthy)` or restarting, check its logs.

## Database Backup and Restore

The `db-backup` service runs automatic backups on a configurable interval (default: every 24 hours, controlled by `BACKUP_INTERVAL_DAYS` in `.env`). Backups are stored in the `db_backups` Docker volume.

**List available backups:**

```bash
docker compose exec db-backup ls -lh /backups/
```

**Create a manual backup:**

```bash
docker compose exec db-backup /backup.sh
```

**Restore from a backup:**

```bash
# Stop services that write to the database
docker compose stop scraper processor pricing_engine api

# Copy the backup file out of the volume
docker compose cp db-backup:/backups/<backup-filename> ./restore.sql.gz

# Drop and recreate the database, then restore
docker compose exec postgres bash -c "
  dropdb -U \$POSTGRES_USER \$POSTGRES_DB &&
  createdb -U \$POSTGRES_USER \$POSTGRES_DB &&
  gunzip -c /backups/<backup-filename> | psql -U \$POSTGRES_USER \$POSTGRES_DB
"

# Restart all services
docker compose up -d
```

Backup retention is controlled by `BACKUP_RETENTION_DAYS` (default: 7).

## Redis Inspection

Connect to the Redis CLI:

```bash
docker compose exec redis redis-cli -a $REDIS_PASSWORD
```

Or if your shell does not expand the variable:

```bash
docker compose exec redis redis-cli -a sse_redis_dev_password
```

**Useful commands once connected:**

```
# Check staleness timestamps
GET sse:staleness:last_scrape
GET sse:staleness:last_sentiment_calc

# List all keys matching a pattern
KEYS sse:*

# Check Redis memory usage
INFO memory

# Monitor commands in real time (caution: verbose)
MONITOR
```

## Common Issues

### Service not starting

Check which containers are running and their status:

```bash
docker compose ps
```

If a container is in a restart loop, check its logs:

```bash
docker compose logs --tail=50 <service-name>
```

Common causes:
- PostgreSQL or Redis not yet healthy (dependent services wait for health checks)
- Invalid environment variables in `.env`
- Port conflicts (another process using 5432, 6379, 8000, or 3000)

### Sentiment prices not updating

1. Check if the scraper is running and fetching posts:
   ```bash
   docker compose logs --tail=20 scraper
   ```

2. Verify the processor received the scraper event and is analyzing posts:
   ```bash
   docker compose logs --tail=20 processor
   ```

3. Check that the pricing engine received the sentiment event:
   ```bash
   docker compose logs --tail=20 pricing_engine
   ```

4. Verify Redis connectivity (pub/sub chain depends on it):
   ```bash
   docker compose exec redis redis-cli -a $REDIS_PASSWORD ping
   ```
   Should return `PONG`.

5. Check if data exists in the database:
   ```bash
   docker compose exec postgres psql -U sse_admin -d sse -c "SELECT count(*) FROM reddit_raw;"
   docker compose exec postgres psql -U sse_admin -d sse -c "SELECT count(*) FROM sentiment_prices;"
   ```

### Frontend not loading or showing stale data

1. Verify the API is responding:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

2. Check CORS configuration -- ensure your frontend URL is listed in `API_CORS_ORIGINS` in `.env`.

3. Hard-refresh the browser (Ctrl+Shift+R) to bypass cached assets.

### Out of memory errors (processor)

The processor service loads FinBERT model weights (~1.4 GB). It has a 4 GB memory limit with a 1.5 GB reservation. If you see OOM kills, check `docker compose logs processor` and consider increasing the memory limit in `docker-compose.yml`.
