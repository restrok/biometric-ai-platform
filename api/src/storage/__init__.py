"""Storage module for Biometric AI Platform."""

from src.storage.base import StorageEngine
from src.storage.factory import get_storage_engine, reset_storage_engine
from src.storage.gcp_engine import GCPStorageEngine
from src.storage.local_engine import LocalStorageEngine

__all__ = [
    "StorageEngine",
    "GCPStorageEngine",
    "LocalStorageEngine",
    "get_storage_engine",
    "reset_storage_engine",
]
