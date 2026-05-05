import json
import logging

from garmin_training_toolkit_sdk.utils import DI_CLIENT_IDS, find_token_file, save_tokens
from garminconnect import Garmin

log = logging.getLogger(__name__)


def refresh_garmin_tokens() -> bool:
    """
    Manually refreshes Garmin tokens using multi-client ID rotation
    and persists the new tokens to the local token file.
    """
    token_file = find_token_file()
    if not token_file:
        log.warning("No local Garmin tokens found to refresh.")
        return False

    try:
        with open(token_file) as f:
            tokens = json.load(f)
    except Exception as e:
        log.error(f"Failed to read Garmin tokens from {token_file}: {e}")
        return False

    success = False
    new_tokens = None

    for client_id in DI_CLIENT_IDS:
        log.info(f"Attempting session refresh with client ID: {client_id}")
        client = Garmin()
        try:
            # Load current tokens into the garminconnect client
            client.client.loads(json.dumps(tokens))
            client.client.di_client_id = client_id

            # This is the internal SDK/garminconnect method that rotates the token
            client.client._refresh_di_token()

            # Get the new token state
            new_tokens_json = client.client.dumps()
            new_tokens = json.loads(new_tokens_json)

            log.info(f"Successfully refreshed Garmin session using {client_id}")
            success = True
            break
        except Exception as e:
            log.debug(f"Refresh failed for client {client_id}: {e}")
            continue

    if success and new_tokens:
        # Update local cache
        try:
            save_tokens(new_tokens)
            return True
        except Exception as e:
            log.error(f"Failed to save refreshed tokens: {e}")
            return False

    log.error("Garmin token refresh failed for all available client IDs.")
    return False
