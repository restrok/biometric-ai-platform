"""Local Secure Credential Vault using AES-128/256-GCM / Fernet symmetric encryption.

Ensures that biometric OAuth tokens (Garmin SSO, Fitbit, Google Health)
are never persisted in plaintext on disk in local-first mode.
"""

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

log = logging.getLogger(__name__)

_global_vault: "LocalSecureVault | None" = None


class LocalSecureVault:
    """Manages encrypted storage of user credentials and API tokens with zero plaintext on disk."""

    def __init__(self, vault_dir: Path | str | None = None, secret_key: str | None = None):
        raw_base = vault_dir or os.getenv("LOCAL_STORAGE_DIR") or os.getenv("BIOMETRIC_DATA_DIR")
        if raw_base:
            storage_base = Path(raw_base)
        elif Path("/app/data").exists() and os.access("/app/data", os.W_OK):
            storage_base = Path("/app/data")
        else:
            storage_base = Path(__file__).resolve().parent.parent.parent / "data"

        storage_base.mkdir(parents=True, exist_ok=True)

        self.vault_dir = storage_base / "vault"
        self.vault_dir.mkdir(parents=True, exist_ok=True)

        # Primary master key file located directly at .vault_key
        self.key_file = storage_base / ".vault_key"
        self._fernet = self._init_fernet(secret_key)

    def _init_fernet(self, secret_key: str | None) -> Fernet:
        """Initializes or loads the Fernet encryption cipher."""
        if secret_key:
            try:
                return Fernet(secret_key.encode() if isinstance(secret_key, str) else secret_key)
            except Exception as e:
                log.warning(f"Could not initialize Fernet from provided secret_key: {e}")

        # Check environment variable
        env_key = os.getenv("VAULT_SECRET_KEY")
        if env_key:
            try:
                return Fernet(env_key.encode())
            except Exception as e:
                log.warning(f"Could not initialize Fernet from VAULT_SECRET_KEY: {e}")

        if self.key_file.exists():
            key = self.key_file.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            with contextlib.suppress(Exception):
                os.chmod(self.key_file, 0o600)
            log.info(f"🔐 Generated new local encryption master key at '{self.key_file}'.")

        return Fernet(key)

    def store_tokens(self, provider: str, user_id: str, tokens: dict[str, Any] | str) -> Path:
        """Encrypts and securely stores tokens for a specific provider and user.

        Strictly persists ONLY an encrypted .enc file on disk.
        """
        prov = provider.lower().replace("-", "_")
        if isinstance(tokens, str):
            try:
                payload = json.dumps(json.loads(tokens))
            except Exception:
                payload = json.dumps({"raw_token": tokens})
        else:
            payload = json.dumps(tokens)

        encrypted = self._fernet.encrypt(payload.encode("utf-8"))
        target_file = self.vault_dir / f"{prov}_tokens_{user_id}.enc"
        target_file.write_bytes(encrypted)
        with contextlib.suppress(Exception):
            os.chmod(target_file, 0o600)

        log.info(f"🔒 Tokens for '{prov}' user '{user_id}' encrypted and stored in vault at '{target_file.name}'.")
        return target_file

    def retrieve_tokens(self, provider: str, user_id: str) -> dict[str, Any] | None:
        """Retrieves and decrypts tokens for a specific provider and user.

        If a legacy unencrypted JSON file exists on disk, it is migrated to .enc and unlinked.
        """
        prov = provider.lower().replace("-", "_")
        enc_file = self.vault_dir / f"{prov}_tokens_{user_id}.enc"

        if enc_file.exists():
            try:
                raw_bytes = self._fernet.decrypt(enc_file.read_bytes())
                return json.loads(raw_bytes.decode("utf-8"))
            except Exception as e:
                log.error(f"Failed to decrypt vault tokens for {prov}:{user_id}: {e}")
                return None

        # Backwards compatibility & automatic migration from legacy plaintext paths
        legacy_dirs = {
            "garmin": [Path.home() / ".garminconnect", Path("/root/.garminconnect")],
            "fitbit": [Path.home() / ".fitbit", Path("/root/.fitbit")],
            "google_health": [Path.home() / ".google_health", Path("/root/.google_health")],
            "google": [Path.home() / ".google_health", Path("/root/.google_health")],
        }
        for d in legacy_dirs.get(prov, []):
            legacy_file = d / f"{prov}_tokens_{user_id}.json"
            if not legacy_file.exists() and prov == "garmin":
                legacy_file = d / f"garmin_tokens_{user_id}.json"
            if legacy_file.exists():
                try:
                    data = json.loads(legacy_file.read_text())
                    # Auto-migrate legacy token into encrypted vault and remove plaintext file
                    self.store_tokens(prov, user_id, data)
                    with contextlib.suppress(Exception):
                        legacy_file.unlink()
                        log.info(f"🧹 Unlinked plaintext legacy token file '{legacy_file}'.")
                    return data
                except Exception as e:
                    log.warning(f"Failed to migrate legacy token file '{legacy_file}': {e}")

        return None

    def list_users(self, provider: str) -> list[str]:
        """Lists user IDs that have encrypted credentials stored for the given provider."""
        prov = provider.lower().replace("-", "_")
        prefix = f"{prov}_tokens_"
        suffix = ".enc"
        users = []
        if self.vault_dir.exists():
            for f in self.vault_dir.glob(f"{prefix}*{suffix}"):
                uid = f.name[len(prefix) : -len(suffix)]
                if uid:
                    users.append(uid)
        return users

    def delete_user_tokens(self, user_id: str) -> list[str]:
        """Deletes all encrypted credentials stored for the specified user across all providers."""
        deleted = []
        suffix = f"_tokens_{user_id}.enc"
        if self.vault_dir.exists():
            for f in list(self.vault_dir.glob(f"*{suffix}")):
                try:
                    f.unlink()
                    deleted.append(f.name)
                    log.info(f"🗑️ Deleted vault token: {f.name}")
                except Exception as e:
                    log.error(f"Failed deleting {f.name}: {e}")
        return deleted

    def has_tokens(self, provider: str, user_id: str) -> bool:
        """Checks if encrypted credentials exist for the user without full decryption."""
        prov = provider.lower().replace("-", "_")
        enc_file = self.vault_dir / f"{prov}_tokens_{user_id}.enc"
        return enc_file.exists()


def get_vault() -> LocalSecureVault:
    """Returns the singleton instance of LocalSecureVault."""
    global _global_vault
    if _global_vault is None:
        _global_vault = LocalSecureVault()
    return _global_vault


def reset_vault() -> None:
    """Resets the singleton vault instance (useful for tests)."""
    global _global_vault
    _global_vault = None
