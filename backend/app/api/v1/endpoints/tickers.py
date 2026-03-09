"""GET /api/v1/tickers/{ticker}/history with optional ?configs= scenario overlay"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import HistoryResponse, PricePoint, ScenarioDataPoint

router = APIRouter()
logger = logging.getLogger(__name__)

_SHIFT_LIMITS = {"1d": 23, "1w": 6, "1m": 29}
# H-1: whitelist dict — bucket interval is NEVER taken from user input
_TIMEFRAME_BUCKET = {"1d": "1 hour", "1w": "1 day", "1m": "1 week"}
_INTERVAL_MAP = {"1d": "5 minutes", "1w": "1 hour", "1m": "4 hours"}
_SHIFT_UNITS = {"1d": "hours", "1w": "days", "1m": "days"}


@router.get(
    "/{ticker}/history",
    response_model=HistoryResponse,
    summary="Ticker price history with optional scenario overlay",
)
async def ticker_history(
    ticker: str,
    request: Request,
    timeframe: str = Query(default="1d", pattern="^(1d|1w|1m)$"),
    shift: int = Query(default=0, ge=0),
    configs: Optional[str] = Query(default=None, description="Comma-separated config slugs"),
) -> HistoryResponse:
    ticker = ticker.upper()
    tf = timeframe.lower()

    # H-1: tf is already validated by the Query regex above, but we do a dict
    # lookup so the interval literal that reaches SQL is always from this
    # whitelist, never from user-supplied text.
    if tf not in _TIMEFRAME_BUCKET:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe '{tf}'")
    bucket = _TIMEFRAME_BUCKET[tf]

    shift_max = _SHIFT_LIMITS[tf]
    shift_unit = _SHIFT_UNITS[tf]

    if shift > shift_max:
        raise HTTPException(
            status_code=422,
            detail=f"shift must be 0\u2013{shift_max} for timeframe {tf}",
        )

    pool: asyncpg.Pool = request.app.state.db_pool

    # Validate ticker exists
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM tickers WHERE symbol = $1 AND is_active = true", ticker
        )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")

    # Time window based on timeframe
    window_map = {"1d": "1 day", "1w": "7 days", "1m": "30 days"}
    window = window_map[tf]
    # H-1: use whitelisted bucket value (never the raw user string)
    display_interval = _INTERVAL_MAP[tf]
    shift_interval = (
        f"{shift} hours" if shift_unit == "hours" else f"{shift} days"
    )

    async with pool.acquire() as conn:
        # H-1: bucket is from _TIMEFRAME_BUCKET whitelist, not user input
        rows = await conn.fetch(
            f"""
            SELECT
                time_bucket('{bucket}', time) AS bucket,
                last(sentiment_price, time) AS sentiment_price,
                last(real_price_at_calc, time) AS real_price,
                last(sentiment_delta, time) AS sentiment_delta
            FROM sentiment_prices
            WHERE ticker = $1
              AND time >= now() - INTERVAL '{window}'
            GROUP BY bucket
            ORDER BY bucket
            """,
            ticker,
        )

    if shift > 0:
        series = [
            PricePoint(
                time=row["bucket"] + timedelta(hours=shift if shift_unit == "hours" else 0, days=shift if shift_unit == "days" else 0),
                sentiment_price=float(row["sentiment_price"]) if row["sentiment_price"] is not None else None,
                real_price=float(row["real_price"]) if row["real_price"] is not None else None,
                sentiment_delta=float(row["sentiment_delta"]) if row["sentiment_delta"] is not None else 0.0,
            )
            for row in rows
        ]
    else:
        series = [
            PricePoint(
                time=row["bucket"],
                sentiment_price=float(row["sentiment_price"]) if row["sentiment_price"] is not None else None,
                real_price=float(row["real_price"]) if row["real_price"] is not None else None,
                sentiment_delta=float(row["sentiment_delta"]) if row["sentiment_delta"] is not None else 0.0,
            )
            for row in rows
        ]

    # Scenario series (optional)
    scenario_series = None
    if configs:
        config_slugs = [s.strip() for s in configs.split(",") if s.strip()]
        if len(config_slugs) > 3:
            raise HTTPException(status_code=422, detail="Maximum 3 configs per request")

        async with pool.acquire() as conn:
            # Validate all slugs exist
            valid_rows = await conn.fetch(
                "SELECT slug, params FROM pricing_configurations"
            )
        valid_slugs = {r["slug"]: r["params"] for r in valid_rows}
        unknown = [s for s in config_slugs if s not in valid_slugs]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown config slugs: {unknown}. Valid: {list(valid_slugs.keys())}",
            )

        # M-2 + M-3: Single query per config slug.
        #
        # M-2 fix: Instead of joining real_prices on an exact time_bucket
        # boundary (which never aligns with actual real_prices.time entries),
        # use a LATERAL subquery that fetches the most-recent real price for
        # the ticker regardless of timestamp alignment.
        #
        # M-3 fix: Apply the correct FormulaEngine formula entirely in SQL:
        #   volume_weight   = ln(1 + mention_count) * volume_weight_multiplier
        #   raw_delta       = avg_sentiment_compound * volume_weight
        #                     * upvote_weight_multiplier * sensitivity
        #   max_delta       = real_price * max_delta_pct
        #   sentiment_price = real_price + GREATEST(LEAST(raw_delta, max_delta), -max_delta)
        #
        # Note: the scenario formula uses avg_sentiment_compound directly
        # (not a score delta vs previous window) because we are computing a
        # "what-if" overlay across a history window, not a live incremental
        # update.  The clamping and multipliers are the critical missing pieces.

        scenario_series = {}
        for slug in config_slugs:
            async with pool.acquire() as conn:
                # M-2: bucket is from _TIMEFRAME_BUCKET whitelist; window is
                # from window_map whitelist — neither is user-supplied text.
                snap_rows = await conn.fetch(
                    f"""
                    SELECT
                        snap.window_end AS ts,
                        snap.avg_sentiment_compound,
                        snap.weighted_mention_count,
                        -- M-2: LATERAL picks the closest preceding real price;
                        -- time_bucket boundaries never align with real_prices.time
                        rp.price AS real_price,
                        -- M-3: full formula matching FormulaEngine exactly
                        ln(1 + snap.weighted_mention_count)
                            * COALESCE((cfg.params->>'volume_weight_multiplier')::float, 1.0)
                            AS volume_weight,
                        rp.price + GREATEST(
                            LEAST(
                                snap.avg_sentiment_compound
                                    * ln(1 + snap.weighted_mention_count)
                                    * COALESCE((cfg.params->>'volume_weight_multiplier')::float, 1.0)
                                    * COALESCE((cfg.params->>'upvote_weight_multiplier')::float, 1.0)
                                    * COALESCE((cfg.params->>'sensitivity')::float, 1.0),
                                rp.price * COALESCE((cfg.params->>'max_delta_pct')::float, 0.10)
                            ),
                            -rp.price * COALESCE((cfg.params->>'max_delta_pct')::float, 0.10)
                        ) AS sentiment_price
                    FROM ticker_sentiment_snapshot AS snap
                    -- M-2: LATERAL subquery — most-recent real price at or before window_end
                    CROSS JOIN LATERAL (
                        SELECT price
                        FROM real_prices
                        WHERE ticker = snap.ticker
                          AND time <= snap.window_end
                        ORDER BY time DESC
                        LIMIT 1
                    ) rp
                    JOIN pricing_configurations AS cfg
                        ON cfg.slug = $2
                    WHERE snap.ticker = $1
                      AND snap.window_end >= now() - INTERVAL '{window}'
                    ORDER BY snap.window_end
                    """,
                    ticker,
                    slug,
                )

            points: list[ScenarioDataPoint] = []
            for snap in snap_rows:
                offset_ts = snap["ts"] + (
                    timedelta(hours=shift) if shift_unit == "hours" else timedelta(days=shift)
                )
                points.append(
                    ScenarioDataPoint(
                        time=offset_ts,
                        sentiment_price=float(snap["sentiment_price"]) if snap["sentiment_price"] is not None else 0.0,
                    )
                )

            scenario_series[slug] = points

    return HistoryResponse(
        ticker=ticker,
        interval=tf,
        series=series,
        scenario_series=scenario_series,
        shift_applied=shift,
        shift_unit=shift_unit,
    )
