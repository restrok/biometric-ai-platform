import base64
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)


def get_secret(secret_id: str, default: str | None = None) -> str | None:
    """
    Retrieves a secret from GCP Secret Manager.
    Falls back to environment variables if Secret Manager fails or is unavailable.
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            log.debug(f"Secret Manager access failed for {secret_id}: {e}")

    # Fallback to environment variables
    # Map secret-manager-style names to env-style names if needed
    env_name = secret_id.upper().replace("-", "_")
    return os.getenv(env_name) or os.getenv(secret_id) or default


def setup_environment():
    """
    Loads environment variables and decodes the AI Studio API Key if necessary.
    Should be called at the entry point of the application or scripts.
    """
    # Find .env file (assuming it's in the api directory)
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)

    # 1. Try to get AI Studio API Key from Secret Manager using configurable name
    secret_name = os.getenv("AISTUDIO_API_KEY_SECRET_NAME", "aistudio-api-key")
    api_key = get_secret(secret_name) or os.getenv("GOOGLE_API_KEY")

    if api_key:
        try:
            # Check if it looks like base64
            decoded_bytes = base64.b64decode(api_key, validate=True)
            decoded_str = decoded_bytes.decode("utf-8")
            if decoded_str.startswith("AIza"):
                os.environ["GOOGLE_API_KEY"] = decoded_str
                log.info("Successfully loaded GOOGLE_API_KEY (AI Studio API Key)")
        except Exception:
            # If it fails to decode, we assume it's already plain text
            os.environ["GOOGLE_API_KEY"] = api_key
            log.info("Successfully loaded GOOGLE_API_KEY from plain text")


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
