"""Storage layer for the SSE worker.

Provides SQLAlchemy async ORM models and store classes for all CRUD
operations against the PostgreSQL database.

Public API
----------
- :class:`.Base` — SQLAlchemy declarative base (used by Alembic)
- :class:`.CollectionRun` — pipeline execution record
- :class:`.DataSource` — configured subreddit
- :class:`.SentimentSignal` — atomic sentiment observation (no PII)
- :class:`.ScoredResult` — derived algorithm output
- :class:`.RunStore` — CRUD for CollectionRun
- :class:`.SignalStore` — CRUD for SentimentSignal
- :class:`.SourceStore` — CRUD for DataSource
"""

from .models import Base, CollectionRun, DataSource, ScoredResult, SentimentSignal
from .runs import RunStore
from .signals import SignalStore
from .sources import SourceStore

__all__ = [
    "Base",
    "CollectionRun",
    "DataSource",
    "RunStore",
    "ScoredResult",
    "SentimentSignal",
    "SignalStore",
    "SourceStore",
]
