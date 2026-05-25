import logging
from google.cloud import firestore
from src.utils.config import get_config

log = logging.getLogger(__name__)

_firestore_client = None

def get_firestore_client():
    """Returns a singleton Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        config = get_config()
        project_id = config.get("project_id")
        log.info(f"Initializing Firestore client for project: {project_id}")
        _firestore_client = firestore.Client(project=project_id)
    return _firestore_client
