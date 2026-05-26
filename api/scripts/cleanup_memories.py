import logging
import os
from pathlib import Path

import google.cloud.firestore as firestore  # type: ignore[attr-defined]
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")


def cleanup():
    db = firestore.Client(project=PROJECT_ID)
    collection_name = "user_memories"

    log.info(f"🧹 Starting cleanup for collection: {collection_name} in project {PROJECT_ID}")

    docs = db.collection(collection_name).stream()
    count = 0

    # Delete in batches would be better for massive scale,
    # but for this cleanup a simple loop is fine.
    for doc in docs:
        log.info(f"  🗑️ Deleting document: {doc.id}")
        doc.reference.delete()
        count += 1

    log.info(f"✅ Finished. Deleted {count} memories.")


if __name__ == "__main__":
    cleanup()
