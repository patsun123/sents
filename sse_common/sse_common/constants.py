"""
SSE project-wide constants.
Single source of truth shared across scraper, processor, pricing_engine, and backend.
"""

# ── Staleness thresholds (minutes / hours) ──────────────────────────────────
STALENESS_WARNING_MINUTES: int = 30
STALENESS_CRITICAL_MINUTES: int = 60
STALENESS_UNAVAILABLE_HOURS: int = 4

# ── NLP backends ─────────────────────────────────────────────────────────────
AVAILABLE_ALGORITHMS: list[str] = ["vader", "textblob", "finbert"]

# ── Pricing ──────────────────────────────────────────────────────────────────
# Starter tickers seeded on first boot (spec §4.4)
STARTER_TICKERS: list[str] = ["TSLA", "NVDA", "GME", "PLTR", "SOFI", "RIVN"]

# ── Market hours (NYSE, ET) ───────────────────────────────────────────────────
MARKET_OPEN_HOUR: int = 9
MARKET_OPEN_MINUTE: int = 30
MARKET_CLOSE_HOUR: int = 16
MARKET_CLOSE_MINUTE: int = 0
MARKET_TIMEZONE: str = "America/New_York"

# ── Data retention ───────────────────────────────────────────────────────────
REDDIT_DATA_RETENTION_DAYS: int = 30

# ── Scraper ──────────────────────────────────────────────────────────────────
DEFAULT_SCRAPE_INTERVAL_MINUTES: int = 15
MAX_SCRAPE_INTERVAL_MINUTES: int = 60

# ── Redis keys ───────────────────────────────────────────────────────────────
REDIS_PRICES_CURRENT_KEY: str = "sse:prices:current"  # Hash: ticker -> JSON price blob
REDIS_SCRAPER_HEALTH_KEY: str = "sse:scraper:health"
REDIS_PROCESSOR_HEALTH_KEY: str = "sse:processor:health"
REDIS_PRICING_HEALTH_KEY: str = "sse:pricing:health"
