# SSE Database User Management

This directory contains SQL scripts for setting up least-privilege PostgreSQL users for the Sentiment Stock Exchange (SSE) project.

## Overview

The SSE project uses five separate database users, each with minimal required privileges. This follows the principle of least privilege to minimize security impact if any service is compromised.

## Database Users

| User | Password Var | Purpose | Privileges |
|------|--------------|---------|-----------|
| `sse_admin` | `changeme_admin` | Alembic database migrations | ALL on ALL tables (migrations only) |
| `sse_api` | `changeme_api` | FastAPI backend server | SELECT on all tables (read-only) |
| `sse_scraper` | `changeme_scraper` | Reddit data scraper service | SELECT, INSERT on `reddit_raw` only |
| `sse_processor` | `changeme_processor` | Sentiment processing service | SELECT on `reddit_raw`; SELECT, INSERT on `comment_sentiment`, `ticker_sentiment_snapshot` |
| `sse_pricing` | `changeme_pricing` | Pricing engine service | SELECT on `ticker_sentiment_snapshot`, `tickers`, `pricing_parameters`, `pricing_configurations`, `real_prices`; SELECT, INSERT on `sentiment_prices` |

## User-to-Table Access Matrix

| Table | sse_admin | sse_api | sse_scraper | sse_processor | sse_pricing |
|-------|-----------|---------|-------------|---------------|-------------|
| `reddit_raw` | ALL | SELECT | SELECT, INSERT | SELECT | — |
| `comment_sentiment` | ALL | SELECT | — | SELECT, INSERT | — |
| `ticker_sentiment_snapshot` | ALL | SELECT | — | SELECT, INSERT | SELECT |
| `tickers` | ALL | SELECT | — | — | SELECT |
| `pricing_parameters` | ALL | SELECT | — | — | SELECT |
| `pricing_configurations` | ALL | SELECT | — | — | SELECT |
| `real_prices` | ALL | SELECT | — | — | SELECT |
| `sentiment_prices` | ALL | SELECT | — | — | SELECT, INSERT |
| `sentiment_scores` | ALL | SELECT | — | — | — |

## Running the Script

### Prerequisites

- PostgreSQL 14+ with the `sse` database already created
- Administrative access (connection as superuser or a user with `CREATEROLE` privilege)

### Execute the Script

```bash
psql -U postgres -d sse -f create_users.sql
```

Or, if you have a custom admin user:

```bash
psql -U your_admin_user -d sse -f create_users.sql
```

The script is **idempotent** — it can be run multiple times without error. Existing roles are not recreated.

## Post-Deployment Actions

### 1. Change All Default Passwords (REQUIRED FOR PRODUCTION)

All users are created with placeholder passwords (`changeme_admin`, `changeme_api`, etc.). Before deploying to production:

```bash
-- Connect as sse_admin (for example)
psql -U sse_admin -d sse
```

Then update each password:

```sql
ALTER ROLE sse_admin WITH PASSWORD 'your_strong_password_here';
ALTER ROLE sse_api WITH PASSWORD 'your_strong_password_here';
ALTER ROLE sse_scraper WITH PASSWORD 'your_strong_password_here';
ALTER ROLE sse_processor WITH PASSWORD 'your_strong_password_here';
ALTER ROLE sse_pricing WITH PASSWORD 'your_strong_password_here';
```

Or use a script:

```bash
#!/bin/bash
# update_passwords.sh

ADMIN_PASS="strong-admin-password"
API_PASS="strong-api-password"
SCRAPER_PASS="strong-scraper-password"
PROCESSOR_PASS="strong-processor-password"
PRICING_PASS="strong-pricing-password"

psql -U postgres -d sse <<EOF
ALTER ROLE sse_admin WITH PASSWORD '$ADMIN_PASS';
ALTER ROLE sse_api WITH PASSWORD '$API_PASS';
ALTER ROLE sse_scraper WITH PASSWORD '$SCRAPER_PASS';
ALTER ROLE sse_processor WITH PASSWORD '$PROCESSOR_PASS';
ALTER ROLE sse_pricing WITH PASSWORD '$PRICING_PASS';
EOF
```

### 2. Store Passwords Securely

- Use environment variables or a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)
- Never commit passwords to version control
- Rotate passwords regularly (monthly recommended)

### 3. Verify User Privileges

After running the script, verify that privileges are correctly assigned:

```bash
psql -U sse_admin -d sse -c "\du"
```

This lists all roles and their attributes.

To view specific table privileges:

```sql
-- List all role privileges on a specific table
SELECT grantee, privilege_type
FROM role_table_grants
WHERE table_name = 'reddit_raw'
ORDER BY grantee, privilege_type;
```

## Important Notes

### sse_admin Usage

The `sse_admin` user is intended **for Alembic migrations only**. It should:
- **NOT** be used by application services
- **NOT** be exposed in application configuration except for the migration runner
- Be rotated and audited regularly

Application services (`sse_api`, `sse_scraper`, `sse_processor`, `sse_pricing`) use their own dedicated accounts.

### Read-Only sse_api

The `sse_api` user (FastAPI backend) is strictly read-only. It cannot:
- INSERT, UPDATE, or DELETE data
- Modify table structure
- Create new objects

This prevents accidental or malicious data corruption by the API server.

### Idempotency

All CREATE ROLE statements use the `IF NOT EXISTS` pattern, making the script safe to run multiple times. However, once created, user passwords cannot be changed by re-running this script. Use `ALTER ROLE` to change passwords.

### Forward Compatibility

The script grants privileges to specific tables by name. When new tables are added:
1. Ensure the table is created
2. Default privileges on new tables are automatically applied per the `ALTER DEFAULT PRIVILEGES` statements
3. For exceptions (e.g., a new table that only `sse_processor` should access), add explicit GRANT statements

## Troubleshooting

### "role sse_admin already exists" when creating

This is normal on a re-run. The script uses `IF NOT EXISTS` to prevent errors.

### "Permission denied for schema public"

Ensure all users have USAGE privilege on the public schema:

```sql
GRANT USAGE ON SCHEMA public TO sse_api, sse_scraper, sse_processor, sse_pricing;
```

### "User cannot insert into table"

Verify the user has INSERT privilege:

```sql
GRANT INSERT ON TABLE table_name TO role_name;
```

### Connection Refused

Ensure:
- PostgreSQL is running
- The `sse` database exists
- The connecting user has appropriate credentials

## Related Files

- `../migrations/` — Alembic migration directory; run with `sse_admin` account
- `../../backend/app/core/config.py` — Configure database URLs for each service
- `../../.env.example` — Environment variable documentation
