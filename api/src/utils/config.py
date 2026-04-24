import base64
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)


def setup_environment():
    """
    Loads environment variables and decodes the Google API Key if necessary.
    Should be called at the entry point of the application or scripts.
    """
    # Find .env file (assuming it's in the api directory)
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)

    # Decode GOOGLE_API_KEY if it's base64 encoded
    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
        try:
            # Check if it looks like base64
            decoded_bytes = base64.b64decode(api_key, validate=True)
            decoded_str = decoded_bytes.decode("utf-8")
            if decoded_str.startswith("AIza"):
                os.environ["GOOGLE_API_KEY"] = decoded_str
                log.info("Successfully decoded GOOGLE_API_KEY from base64")
        except Exception:
            # If it fails to decode, we assume it's already plain text
            pass


def get_config():
    """
    Returns common configuration values.
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        # Don't raise error here, let the caller decide if it's critical
        log.warning("GOOGLE_CLOUD_PROJECT environment variable is not set.")

    return {
        "project_id": project_id,
        "dataset_id": os.getenv("BQ_DATASET", "biometric_data_dev"),
        "knowledge_base_table": os.getenv("BQ_KB_TABLE", "knowledge_base"),
        "finops_table": os.getenv("BQ_FINOPS_TABLE", "finops_logs"),
    }
