import json
import logging
import os
from pathlib import Path

from garmin_training_toolkit_sdk.utils import DI_CLIENT_IDS
from garminconnect import Garmin

from src.utils.config import get_config, get_secret, set_secret
from src.utils.notifications import send_proactive_notification

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
    
    any_attempted = False
    all_success = True

    for user_id in user_ids:
        # Check if user has tokens before attempting refresh
        secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
        secret_name = f"{secret_base_name}-{user_id}"
        
        token_json = get_secret(secret_name)
        file_exists = (Path.home() / ".garminconnect" / f"garmin_tokens_{user_id}.json").exists() or \
                      (Path("/root/.garminconnect") / f"garmin_tokens_{user_id}.json").exists()

        if not token_json and not file_exists:
            log.debug(f"Skipping user {user_id}: no tokens found.")
            continue

        any_attempted = True
        if not refresh_user_token(user_id):
            all_success = False

    return all_success if any_attempted else True


def refresh_user_token(user_id: str) -> bool:
    """
    Refreshes Garmin tokens for a specific user.
    """
    log.info(f"🕒 Refreshing tokens for user: {user_id}")

    # 1. Try to load tokens (Secret Manager -> Local File)
    tokens = None
    original_source = None  # 'secret' or 'file'
    working_source_path = None
    
    secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
    secret_name = f"{secret_base_name}-{user_id}"
    
    # A. Check Secret Manager
    token_json = get_secret(secret_name)
    if token_json:
        try:
            tokens = json.loads(token_json)
            original_source = "secret"
            log.debug(f"Loaded tokens for {user_id} from Secret Manager.")
        except Exception as e:
            log.warning(f"Failed to parse secret for {user_id}: {e}")

    # Helper to load from file
    def get_tokens_from_file():
        possible_files = [
            Path.home() / ".garminconnect" / f"garmin_tokens_{user_id}.json",
            Path("/root/.garminconnect") / f"garmin_tokens_{user_id}.json",
        ]
        for pf in possible_files:
            if pf.exists():
                try:
                    with open(pf) as f:
                        return json.load(f), pf
                except Exception as e:
                    log.warning(f"Failed to read file {pf}: {e}")
        return None, None

    # 2. Refresh Attempt Logic
    def attempt_refresh(tokens_to_refresh):
        for client_id in DI_CLIENT_IDS:
            client = Garmin()
            try:
                client.client.loads(json.dumps(tokens_to_refresh))
                client.client.di_client_id = client_id
                client.client._refresh_di_token()
                log.info(f"✅ Successfully refreshed session for {user_id} using {client_id}")
                return json.loads(client.client.dumps())
            except Exception as e:
                log.debug(f"Refresh failed for {user_id} with {client_id}: {e}")
                continue
        return None

    # B. Try Refreshing what we have
    refreshed_tokens = None
    if tokens:
        refreshed_tokens = attempt_refresh(tokens)

    # C. Fallback: If Secret Manager refresh failed (or no secret), try local file
    if not refreshed_tokens:
        if original_source == "secret":
            log.info(f"🔄 SM tokens for {user_id} failed. Attempting local file fallback...")
        
        file_tokens, file_path = get_tokens_from_file()
        if file_tokens:
            refreshed_tokens = attempt_refresh(file_tokens)
            if refreshed_tokens:
                working_source_path = file_path

    # 3. Save back (Update Secret Manager AND Local File if possible)
    if refreshed_tokens:
        # Always try to update Secret Manager if the user is supposed to have one
        if original_source == "secret" or os.getenv("GOOGLE_CLOUD_PROJECT"):
            if not set_secret(secret_name, json.dumps(refreshed_tokens)):
                log.error(f"❌ Failed to update secret for {user_id}")
                # We don't return False here if file update might still work
            else:
                log.info(f"✨ Repaired/Updated Secret Manager for {user_id}")

        # Also update local file if we have one
        target_file = working_source_path or Path("/root/.garminconnect") / f"garmin_tokens_{user_id}.json"
        try:
            # Ensure directory exists
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, "w") as f:
                json.dump(refreshed_tokens, f, indent=4)
            log.debug(f"Updated local file for {user_id}: {target_file}")
        except Exception as e:
            log.warning(f"Failed to update local file for {user_id}: {e}")
            # If secret worked, we still consider it a success
        
        return True

    log.error(f"❌ Failed to refresh tokens for user {user_id} after trying all clients.")
    send_proactive_notification(
        user_id,
        "🚨 *Error de Sincronización*: No pude renovar tu sesión de Garmin automáticamente. "
        "Por favor, ejecutá `/garmin_login` para volver a vincular tu cuenta.",
    )
    return False
