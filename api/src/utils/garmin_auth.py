import json
import logging
from pathlib import Path

from garmin_training_toolkit_sdk.utils import DI_CLIENT_IDS, find_token_file
from garminconnect import Garmin

log = logging.getLogger(__name__)


def get_all_garmin_user_ids() -> list[str]:
    """
    Scans the token directories and returns a list of user IDs found.
    Extracts {user_id} from garmin_tokens_{user_id}.json.
    """
    possible_dirs = [
        Path("/root/.garminconnect"),
        Path.home() / ".garminconnect",
    ]

    user_ids = set()
    for d in possible_dirs:
        try:
            if d.exists():
                for f in d.glob("garmin_tokens_*.json"):
                    # Extract 'fsirio' from 'garmin_tokens_fsirio.json'
                    user_id = f.name.replace("garmin_tokens_", "").replace(".json", "")
                    if user_id:
                        user_ids.add(user_id)
        except PermissionError:
            log.debug(f"Permission denied for directory: {d}")
            continue

    return list(user_ids)


def refresh_garmin_tokens() -> bool:
    """
    Manually refreshes all Garmin tokens found in the token directories.
    Scans for garmin_tokens*.json and refreshes each session using
    multi-client ID rotation.
    """
    # 1. Identify all potential token files
    # We check common locations since find_token_file() might fail in some container envs
    possible_dirs = [
        Path("/root/.garminconnect"),
        Path.home() / ".garminconnect",
    ]

    # Also add the path from find_token_file if it finds anything
    primary = find_token_file()
    if primary:
        possible_dirs.append(Path(primary).parent)

    token_files = []
    checked_dirs = set()

    for d in possible_dirs:
        try:
            if d.exists() and d not in checked_dirs:
                token_files.extend(list(d.glob("garmin_tokens*.json")))
                # Also check for the legacy name if no user-specific ones found
                if not token_files:
                    legacy = d / "garmin_tokens.json"
                    if legacy.exists():
                        token_files.append(legacy)
                checked_dirs.add(d)
        except PermissionError:
            log.debug(f"Permission denied for directory: {d}")
            continue

    if not token_files:
        log.warning("No Garmin token files found to refresh.")
        return False

    log.info(f"🔄 Found {len(token_files)} Garmin token files to refresh.")

    all_success = True
    for token_file in token_files:
        log.info(f"🕒 Refreshing: {token_file.name}")
        try:
            with open(token_file) as f:
                tokens = json.load(f)
        except Exception as e:
            log.error(f"Failed to read tokens from {token_file}: {e}")
            all_success = False
            continue

        success = False
        new_tokens = None

        for client_id in DI_CLIENT_IDS:
            log.debug(f"Attempting refresh with client ID: {client_id}")
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

                log.info(f"✅ Successfully refreshed session in {token_file.name} using {client_id}")
                success = True
                break
            except Exception as e:
                log.debug(f"Refresh failed for client {client_id}: {e}")
                continue

        if success and new_tokens:
            try:
                # Save specifically to the source file
                with open(token_file, "w") as f:
                    json.dump(new_tokens, f, indent=4)
            except Exception as e:
                log.error(f"Failed to save refreshed tokens to {token_file}: {e}")
                all_success = False
        else:
            log.error(f"❌ Failed to refresh {token_file.name} for all available client IDs.")
            all_success = False

    return all_success
