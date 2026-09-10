import logging
import time
from pathlib import Path

from app.core.config import Settings

logger = logging.getLogger("uvicorn.error")


def evict_stale_cache(settings: Settings) -> None:
    cache_dir: Path = settings.cache_dir
    if not cache_dir.exists():
        return

    cutoff = time.time() - settings.cache_ttl_days * 86_400
    removed = 0
    freed_bytes = 0

    for entry in cache_dir.rglob("*"):
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            try:
                freed_bytes += stat.st_size
                entry.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Cache eviction: could not remove %s: %s", entry, exc)

    if removed:
        logger.info(
            "Cache eviction: removed %d stale file(s), freed %.1f MB "
            "(TTL=%d days, dir=%s)",
            removed,
            freed_bytes / 1024 / 1024,
            settings.cache_ttl_days,
            cache_dir,
        )
    else:
        logger.debug(
            "Cache eviction: no stale files found (TTL=%d days, dir=%s)",
            settings.cache_ttl_days,
            cache_dir,
        )
