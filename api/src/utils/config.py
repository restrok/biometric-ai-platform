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


def set_secret(secret_id: str, payload: str) -> bool:
    """
    Updates a secret in GCP Secret Manager by adding a new version.
    If the secret doesn't exist, it attempts to create it (if permissions allow).
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        log.warning(f"GOOGLE_CLOUD_PROJECT not set. Cannot update secret {secret_id}.")
        return False

    try:
        from google.api_core import exceptions
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent_project = f"projects/{project_id}"
        secret_path = f"{parent_project}/secrets/{secret_id}"

        # 1. Check if secret exists, if not create it
        try:
            client.get_secret(request={"name": secret_path})
        except exceptions.NotFound:
            log.info(f"Creating missing secret: {secret_id}")
            client.create_secret(
                request={
                    "parent": parent_project,
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}},
                }
            )

        # 2. Add the secret version
        response = client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": payload.encode("UTF-8")},
            }
        )

        log.info(f"✅ Successfully updated secret version: {response.name}")

        # CLEANUP: Only keep a limited number of versions to stay in free tier
        # We try to disable/destroy older versions if possible
        try:
            versions = client.list_secret_versions(request={"parent": secret_path})
            # Sort by create_time or name (higher index is newer)
            active_versions = [v for v in versions if v.state.name == "ENABLED"]
            if len(active_versions) > 5:
                # Destroy oldest enabled version
                oldest = sorted(active_versions, key=lambda v: v.name)[0]
                client.destroy_secret_version(request={"name": oldest.name})
                log.info(f"🧹 Destroyed old secret version to save quota: {oldest.name}")
        except Exception as e:
            log.debug(f"Secret version cleanup failed (non-critical): {e}")

        return True
    except Exception as e:
        log.error(f"❌ Failed to update secret {secret_id} in Secret Manager: {e}")
        return False


def setup_environment():
    """
    Loads environment variables and decodes the AI Studio API Key if necessary.
    Should be called at the entry point of the application or scripts.
    """
    # Find .env file (assuming it's in the api directory)
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)

    # Set system timezone if TZ is provided
    tz = os.getenv("TZ")
    if tz:
        try:
            import time
            os.environ["TZ"] = tz
            time.tzset()
            log.info(f"🌍 Timezone set to: {tz} ({time.strftime('%Z %z')})")
        except Exception as e:
            log.warning(f"Failed to set timezone {tz}: {e}")

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
