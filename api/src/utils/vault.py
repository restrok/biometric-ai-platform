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
    """Manages encrypted storage of user credentials and API tokens."""

    def __init__(self, vault_dir: Path | str | None = None, secret_key: str | None = None):
        storage_base = vault_dir or os.getenv("LOCAL_STORAGE_DIR") or str(Path.home() / ".secure_vault")
        self.vault_dir = Path(storage_base) / "vault"
        self.vault_dir.mkdir(parents=True, exist_ok=True)

        self.key_file = self.vault_dir / ".vault_key"
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
            log.info("🔐 Generated new local encryption master key for credential vault.")

        return Fernet(key)

    def store_tokens(self, provider: str, user_id: str, tokens: dict[str, Any] | str) -> Path:
        """Encrypts and securely stores tokens for a specific provider and user."""
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

        log.info(f"🔒 Tokens for '{prov}' user '{user_id}' encrypted and stored in vault.")
        return target_file

    def retrieve_tokens(self, provider: str, user_id: str) -> dict[str, Any] | None:
        """Retrieves and decrypts tokens for a specific provider and user.

        Falls back to legacy unencrypted paths for seamless backwards-compatibility.
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

        # Backwards compatibility: check legacy plaintext paths
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
                    # Auto-migrate legacy token into encrypted vault
                    self.store_tokens(prov, user_id, data)
                    return data
                except Exception:
                    pass

        return None


def get_vault() -> LocalSecureVault:
    """Returns the singleton instance of LocalSecureVault."""
    global _global_vault
    if _global_vault is None:
        _global_vault = LocalSecureVault()
    return _global_vault
