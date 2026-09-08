import logging
from typing import Any

from src.utils.config import get_config

log = logging.getLogger(__name__)

_firestore_client = None


def get_firestore_client():
    """Returns a singleton Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        import google.cloud.firestore as firestore  # type: ignore[attr-defined]

        config = get_config()
        project_id = config.get("project_id")
        log.info(f"Initializing Firestore client for project: {project_id}")
        _firestore_client = firestore.Client(project=project_id)
    return _firestore_client


def get_user_profile(user_id: str) -> dict[str, Any]:
    """Retrieves a user profile from the configured storage engine."""
    from src.storage.factory import get_storage_engine

    return get_storage_engine().get_user_profile(user_id)


def update_user_profile(user_id: str, data: dict[str, Any]):
    """Updates or creates a user profile in the configured storage engine."""
    from src.storage.factory import get_storage_engine

    get_storage_engine().update_user_profile(user_id, data)
    log.info(f"✅ Updated profile for user: {user_id}")
