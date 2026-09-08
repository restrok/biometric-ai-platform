"""Storage module for Biometric AI Platform."""

from src.storage.base import StorageEngine
from src.storage.factory import get_storage_engine, reset_storage_engine

__all__ = [
    "StorageEngine",
    "get_storage_engine",
    "reset_storage_engine",
]
