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


def get_user_profile(user_id: str) -> dict:
    """Retrieves a user profile from Firestore."""
    db = get_firestore_client()
    doc_ref = db.collection("user_profiles").document(user_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return {}


def update_user_profile(user_id: str, data: dict):
    """Updates or creates a user profile in Firestore."""
    db = get_firestore_client()
    doc_ref = db.collection("user_profiles").document(user_id)
    doc_ref.set(data, merge=True)
    log.info(f"✅ Updated Firestore profile for user: {user_id}")
