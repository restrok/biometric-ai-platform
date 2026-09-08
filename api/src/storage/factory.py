"""Storage engine factory supporting dynamic switching between GCP and Local-First."""

import logging
import os
from typing import Literal

from src.storage.base import StorageEngine

log = logging.getLogger(__name__)

_storage_engine: StorageEngine | None = None


def get_storage_engine(mode: Literal["gcp", "local"] | None = None) -> StorageEngine:
    """Returns the configured StorageEngine singleton (GCPStorageEngine or LocalStorageEngine)."""
    global _storage_engine
    if _storage_engine is not None and mode is None:
        return _storage_engine

    raw_mode = mode or os.getenv("STORAGE_MODE") or "gcp"
    target_mode = raw_mode.lower()

    if target_mode == "local":
        from src.storage.local_engine import LocalStorageEngine

        log.info("🔌 Using LocalStorageEngine (SQLite + DuckDB)")
        _storage_engine = LocalStorageEngine()
    else:
        from src.storage.gcp_engine import GCPStorageEngine

        log.info("☁️ Using GCPStorageEngine (Firestore + BigQuery)")
        _storage_engine = GCPStorageEngine()

    return _storage_engine


def reset_storage_engine() -> None:
    """Resets the singleton storage engine (primarily for testing)."""
    global _storage_engine
    _storage_engine = None
