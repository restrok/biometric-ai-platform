import json
import logging
import os
from pathlib import Path

from garmin_training_toolkit_sdk.utils import DI_CLIENT_IDS
from garminconnect import Garmin

from src.utils.config import get_config, get_secret, set_secret

log = logging.getLogger(__name__)


def get_all_garmin_user_ids() -> list[str]:
    """
    Scans the token directories and BigQuery to return a list of all known user IDs.
    """
    user_ids = set()

    # 1. Scan Local Files (Legacy/Dev)
    possible_dirs = [
        Path("/root/.garminconnect"),
        Path.home() / ".garminconnect",
    ]

    for d in possible_dirs:
        try:
            if d.exists():
                for f in d.glob("garmin_tokens_*.json"):
                    user_id = f.name.replace("garmin_tokens_", "").replace(".json", "")
                    if user_id:
                        user_ids.add(user_id)
        except PermissionError:
            continue

    # 2. Scan BigQuery (Source of truth for registered users)
    try:
        from google.cloud import bigquery

        config = get_config()
        client = bigquery.Client(project=config["project_id"])
        query = f"SELECT DISTINCT user_id FROM `{config['project_id']}.{config['dataset_id']}.user_profile` WHERE user_id IS NOT NULL"
        results = client.query(query).result()
        for row in results:
            user_ids.add(row.user_id)
    except Exception as e:
        log.debug(f"Failed to fetch user_ids from BigQuery: {e}")

    # 3. Fallback to default user if nothing found
    if not user_ids:
        default_user = os.getenv("DEFAULT_USER_ID", "fsirio")
        user_ids.add(default_user)

    return list(user_ids)


def refresh_garmin_tokens() -> bool:
    """
    Refreshes Garmin tokens for all users found in Secret Manager or local files.
    """
    user_ids = get_all_garmin_user_ids()
    if not user_ids:
        log.warning("No users found to refresh.")
        return False

    log.info(f"🔄 Starting token refresh for users: {user_ids}")
    all_success = True

    for user_id in user_ids:
        if not refresh_user_token(user_id):
            all_success = False

    return all_success


def refresh_user_token(user_id: str) -> bool:
    """
    Refreshes Garmin tokens for a specific user.
    """
    log.info(f"🕒 Refreshing tokens for user: {user_id}")

    # 1. Try to load tokens (Secret Manager -> Local File)
    tokens = None
    source_type = None  # 'secret' or 'file'
    source_path = None

    # A. Check Secret Manager
    secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
    secret_name = f"{secret_base_name}-{user_id}"
    token_json = get_secret(secret_name)

    if token_json:
        try:
            tokens = json.loads(token_json)
            source_type = "secret"
            log.debug(f"Loaded tokens for {user_id} from Secret Manager.")
        except Exception as e:
            log.warning(f"Failed to parse secret for {user_id}: {e}")

    # B. Check Local File if no secret found
    if not tokens:
        possible_files = [
            Path.home() / ".garminconnect" / f"garmin_tokens_{user_id}.json",
            Path("/root/.garminconnect") / f"garmin_tokens_{user_id}.json",
        ]
        for pf in possible_files:
            if pf.exists():
                try:
                    with open(pf) as f:
                        tokens = json.load(f)
                        source_type = "file"
                        source_path = pf
                        log.debug(f"Loaded tokens for {user_id} from local file: {pf}")
                        break
                except Exception as e:
                    log.warning(f"Failed to read file {pf}: {e}")

    if not tokens:
        log.warning(f"No tokens found for user {user_id}. Skipping.")
        return False

    # 2. Refresh the session
    refreshed_tokens = None
    for client_id in DI_CLIENT_IDS:
        client = Garmin()
        try:
            client.client.loads(json.dumps(tokens))
            client.client.di_client_id = client_id
            client.client._refresh_di_token()
            refreshed_tokens = json.loads(client.client.dumps())
            log.info(f"✅ Successfully refreshed session for {user_id} using {client_id}")
            break
        except Exception as e:
            log.debug(f"Refresh failed for {user_id} with {client_id}: {e}")
            continue

    # 3. Save back to the SAME source
    if refreshed_tokens:
        if source_type == "secret":
            if not set_secret(secret_name, json.dumps(refreshed_tokens)):
                log.error(f"❌ Failed to update secret for {user_id}")
                return False
        elif source_type == "file" and source_path:
            try:
                with open(source_path, "w") as f:
                    json.dump(refreshed_tokens, f, indent=4)
            except Exception as e:
                log.error(f"❌ Failed to save file for {user_id}: {e}")
                return False
        return True
    else:
        log.error(f"❌ Failed to refresh tokens for user {user_id} after trying all clients.")
        return False
