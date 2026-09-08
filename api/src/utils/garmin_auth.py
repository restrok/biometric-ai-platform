import json
import logging
import os
from pathlib import Path

from garmin_training_toolkit_sdk.utils import DI_CLIENT_IDS
from garminconnect import Garmin

from src.utils.config import get_config, get_secret, set_secret
from src.utils.notifications import send_proactive_notification
from src.utils.vault import get_vault

log = logging.getLogger(__name__)


def get_all_garmin_user_ids() -> list[str]:
    """
    Scans the encrypted vault, legacy directories, and BigQuery to return a list of all known user IDs.
    """
    user_ids = set()

    # 1. Scan LocalSecureVault (Encrypted Local Storage)
    try:
        for uid in get_vault().list_users("garmin"):
            user_ids.add(uid)
    except Exception as e:
        log.debug(f"Failed to list vault users: {e}")

    # 2. Scan Local Files (Legacy/Dev fallback)
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

    # 3. Scan BigQuery (Source of truth for registered users in GCP)
    try:
        from google.cloud import bigquery

        config = get_config()
        if config.get("project_id"):
            client = bigquery.Client(project=config["project_id"])
            query = f"SELECT DISTINCT user_id FROM `{config['project_id']}.{config['dataset_id']}.user_profile` WHERE user_id IS NOT NULL"
            results = client.query(query).result()
            for row in results:
                user_ids.add(row.user_id)
    except Exception as e:
        log.debug(f"Failed to fetch user_ids from BigQuery: {e}")

    # 4. Fallback to default user if nothing found
    if not user_ids:
        default_user = os.getenv("DEFAULT_USER_ID", "default_user")
        user_ids.add(default_user)

    return list(user_ids)


def refresh_garmin_tokens() -> bool:
    """
    Refreshes Garmin tokens for all users found in Secret Manager, Vault, or legacy files.
    """
    user_ids = get_all_garmin_user_ids()
    if not user_ids:
        log.warning("No users found to refresh.")
        return False

    log.info(f"🔄 Starting token refresh for users: {user_ids}")

    any_attempted = False
    all_success = True

    for user_id in user_ids:
        secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
        secret_name = f"{secret_base_name}-{user_id}"

        token_json = get_secret(secret_name) if os.getenv("GOOGLE_CLOUD_PROJECT") else None
        has_vault = get_vault().has_tokens("garmin", user_id)
        file_exists = (Path.home() / ".garminconnect" / f"garmin_tokens_{user_id}.json").exists() or (
            Path("/root/.garminconnect") / f"garmin_tokens_{user_id}.json"
        ).exists()

        if not token_json and not has_vault and not file_exists:
            log.debug(f"Skipping user {user_id}: no tokens found.")
            continue

        any_attempted = True
        if not refresh_user_token(user_id):
            all_success = False

    return all_success if any_attempted else True


def refresh_user_token(user_id: str) -> bool:
    """
    Refreshes Garmin tokens for a specific user.
    Prioritizes LocalSecureVault in local environments and Secret Manager in GCP.
    """
    log.info(f"🕒 Refreshing tokens for user: {user_id}")

    tokens = None
    original_source = None  # 'vault', 'secret', or 'file'
    working_source_path = None

    # A. Check LocalSecureVault first (Local encrypted storage)
    vault_tokens = get_vault().retrieve_tokens("garmin", user_id)
    if vault_tokens:
        tokens = vault_tokens
        original_source = "vault"
        log.debug(f"Loaded tokens for {user_id} from LocalSecureVault.")

    # B. Check Secret Manager (if on GCP)
    if not tokens and os.getenv("GOOGLE_CLOUD_PROJECT"):
        secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
        secret_name = f"{secret_base_name}-{user_id}"
        token_json = get_secret(secret_name)
        if token_json:
            try:
                tokens = json.loads(token_json)
                original_source = "secret"
                log.debug(f"Loaded tokens for {user_id} from Secret Manager.")
            except Exception as e:
                log.warning(f"Failed to parse secret for {user_id}: {e}")

    # C. Fallback to legacy unencrypted file
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
                        working_source_path = pf
                        original_source = "file"
                        log.debug(f"Loaded legacy tokens for {user_id} from {pf}")
                        break
                except Exception as e:
                    log.warning(f"Failed to read file {pf}: {e}")

    if not tokens:
        log.warning(f"No existing tokens could be loaded for user {user_id}")
        return False

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

    refreshed_tokens = attempt_refresh(tokens)

    # 3. Save back refreshed tokens
    if refreshed_tokens:
        # A. Always update LocalSecureVault
        try:
            get_vault().store_tokens("garmin", user_id, refreshed_tokens)
            log.info(f"🔒 Persisted refreshed tokens to LocalSecureVault for '{user_id}'.")
        except Exception as e:
            log.warning(f"Failed to store in vault for {user_id}: {e}")

        # B. Update Secret Manager if configured
        if original_source == "secret" or os.getenv("GOOGLE_CLOUD_PROJECT"):
            secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
            secret_name = f"{secret_base_name}-{user_id}"
            if not set_secret(secret_name, json.dumps(refreshed_tokens)):
                log.error(f"❌ Failed to update secret for {user_id}")
            else:
                log.info(f"✨ Repaired/Updated Secret Manager for {user_id}")

        # C. Update legacy file ONLY if it originally came from an unencrypted file and not strictly local mode
        if working_source_path and os.getenv("STORAGE_MODE") != "local":
            try:
                working_source_path.parent.mkdir(parents=True, exist_ok=True)
                with open(working_source_path, "w") as f:
                    json.dump(refreshed_tokens, f, indent=4)
                log.debug(f"Updated legacy file for {user_id}: {working_source_path}")
            except Exception as e:
                log.warning(f"Failed to update legacy file for {user_id}: {e}")

        return True

    log.error(f"❌ Failed to refresh tokens for user {user_id} after trying all clients.")
    send_proactive_notification(
        user_id,
        "🚨 *Error de Sincronización*: No pude renovar tu sesión de Garmin automáticamente. "
        "Por favor, ejecutá `/garmin_login` para volver a vincular tu cuenta.",
    )
    return False
