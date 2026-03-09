"""
Redis pub/sub channel name constants.
Every service that publishes or subscribes MUST import from here — no hardcoded strings.
"""

# Published by the scraper after each successful run batch
CHANNEL_SCRAPER_DONE: str = "sse:scraper:run_complete"

# Published by the processor after sentiment analysis completes for a batch
CHANNEL_PROCESSOR_DONE: str = "sse:sentiment:run_complete"

# Published by the pricing engine after prices are updated
CHANNEL_PRICING_DONE: str = "sse:pricing:run_complete"


# ── Message payload schemas (documented here, not enforced at runtime) ────────
#
# CHANNEL_SCRAPER_DONE payload:
#   { "run_id": str, "tickers_scraped": list[str], "posts_count": int,
#     "timestamp": str (ISO 8601) }
#
# CHANNEL_PROCESSOR_DONE payload:
#   { "run_id": str, "tickers_processed": list[str], "comments_analyzed": int,
#     "timestamp": str }
#
# CHANNEL_PRICING_DONE payload:
#   { "run_id": str, "tickers_priced": list[str], "timestamp": str }
