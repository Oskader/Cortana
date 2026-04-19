"""
Cache con TTL para datos de mercado.
Evita re-descargar datos en cada ciclo de análisis.
"""

from datetime import datetime, timedelta
from typing import Any, Optional


class MarketDataCache:
    """
    Cache key-value con time-to-live configurable.

    Usage:
        cache = MarketDataCache(ttl_seconds=60)
        cache.set("AAPL_1h", df)
        df = cache.get("AAPL_1h")  # None if expired
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._cache: dict[str, tuple[datetime, Any]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a value if it exists and hasn't expired.

        Args:
            key: Cache key.

        Returns:
            Cached value, or None if missing/expired.
        """
        if key in self._cache:
            timestamp, value = self._cache[key]
            if datetime.utcnow() - timestamp < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """
        Store a value with the current timestamp.

        Args:
            key: Cache key.
            value: Value to store.
        """
        self._cache[key] = (datetime.utcnow(), value)

    def invalidate(self, key: str) -> None:
        """Remove a specific key from cache."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Number of entries in cache (including potentially expired)."""
        return len(self._cache)
