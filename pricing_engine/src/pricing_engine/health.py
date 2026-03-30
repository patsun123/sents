"""Re-export HealthServer from sse_common to maintain import compatibility."""
from sse_common.health import HealthServer

__all__ = ["HealthServer"]
