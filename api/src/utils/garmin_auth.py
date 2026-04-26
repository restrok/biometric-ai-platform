import json
import logging
from pathlib import Path

from garmin_training_toolkit_sdk.utils import find_token_file, save_tokens
from garminconnect import Garmin

log = logging.getLogger(__name__)

DI_CLIENT_IDS = (
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2024Q4",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI",
    "GARMIN_CONNECT_MOBILE_IOS_DI",
)


def refresh_garmin_session(token_file: Path) -> bool:
    """
    Attempts to refresh the Garmin session using multiple known client IDs.
    Updates the token file on success.
    """
    if not token_file.exists():
        log.error(f"Token file not found at {token_file}")
        return False

    with open(token_file) as f:
        tokens = json.load(f)

    for client_id in DI_CLIENT_IDS:
        log.info(f"Attempting session refresh with client ID: {client_id}")
        client = Garmin()
        try:
            client.client.loads(json.dumps(tokens))
            client.client.di_client_id = client_id
            client.client._refresh_di_token()

            new_tokens = json.loads(client.client.dumps())
            save_tokens(new_tokens)
            log.info(f"Successfully refreshed Garmin session using {client_id}")
            return True
        except Exception as e:
            log.debug(f"Refresh failed with {client_id}: {e}")

    log.error("Failed to refresh Garmin session with all known client IDs.")
    return False


def get_robust_client(token_file: Path | None = None):
    """
    Returns an authenticated Garmin client, automatically attempting a refresh
    if the initial authentication fails or if the token is expired.
    """
    from garmin_training_toolkit_sdk.utils import get_authenticated_client

    if token_file is None:
        token_file = find_token_file()

    if not token_file:
        raise Exception("Garmin tokens not found. Please authenticate first.")

    try:
        # Try initial authentication
        client = get_authenticated_client(token_file)
        # Test the connection with a lightweight call
        client.get_userprofile_settings()
        return client
    except Exception as e:
        error_str = str(e).lower()
        if "401" in error_str or "unauthorized" in error_str or "expired" in error_str:
            log.info("Authentication failed (401/Expired). Attempting proactive refresh...")
            if refresh_garmin_session(token_file):
                return get_authenticated_client(token_file)
        raise
