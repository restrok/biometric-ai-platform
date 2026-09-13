"""Google Workspace OAuth 2.0 Client with PKCE & Local Vault Encryption.

Supports Read-Only scopes for Google Calendar and Gmail:
- https://www.googleapis.com/auth/calendar.readonly
- https://www.googleapis.com/auth/gmail.readonly

Principles:
- Strict decoupling: client credentials read dynamically from runtime environment (.env), never hardcoded.
- Least privilege: tokens separated per provider ('google_calendar' vs 'google_gmail').
- Encrypted storage: Fernet AES symmetric encryption via LocalSecureVault.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

from src.utils.vault import LocalSecureVault, get_vault

log = logging.getLogger(__name__)

# Google OAuth 2.0 Endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Readonly Scopes
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

DEFAULT_REDIRECT_URI = "http://localhost:8002/auth/google/callback"


def generate_code_verifier(length: int = 64) -> str:
    """Generates a high-entropy cryptographic PKCE code_verifier."""
    return secrets.token_urlsafe(length)[:length]


def generate_code_challenge(verifier: str) -> str:
    """Generates a SHA-256 base64url-encoded PKCE code_challenge."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class GoogleOAuthClient:
    """Handles OAuth 2.0 authorization code flow with PKCE and token lifecycle management."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
        scopes: list[str] | None = None,
    ):
        # Resolve client credentials from environment if not explicitly provided
        self.client_id = (
            client_id
            or os.getenv("GOOGLE_HEALTH_CLIENT_ID")
            or os.getenv("GOOGLE_CLIENT_ID")
            or os.getenv("GOOGLE_WORKSPACE_CLIENT_ID")
            or ""
        )
        self.client_secret = (
            client_secret
            or os.getenv("GOOGLE_HEALTH_CLIENT_SECRET")
            or os.getenv("GOOGLE_CLIENT_SECRET")
            or os.getenv("GOOGLE_WORKSPACE_CLIENT_SECRET")
            or ""
        )
        self.redirect_uri = redirect_uri
        self.scopes = scopes or [CALENDAR_READONLY_SCOPE, GMAIL_READONLY_SCOPE]

    def validate_credentials(self) -> None:
        """Validates that client ID and client secret are configured."""
        if not self.client_id:
            raise ValueError(
                "Google OAuth client_id is missing. Set GOOGLE_HEALTH_CLIENT_ID or GOOGLE_CLIENT_ID in runtime environment."
            )
        if not self.client_secret:
            raise ValueError(
                "Google OAuth client_secret is missing. Set GOOGLE_HEALTH_CLIENT_SECRET or GOOGLE_CLIENT_SECRET in runtime environment."
            )

    def get_authorization_url(
        self,
        state: str | None = None,
        login_hint: str | None = None,
        access_type: str = "offline",
        prompt: str = "consent",
    ) -> tuple[str, str, str]:
        """Generates Google OAuth 2.0 authorization URL with PKCE.

        Returns:
            tuple of (auth_url, code_verifier, state)
        """
        self.validate_credentials()
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        state_val = state or secrets.token_urlsafe(16)

        params: dict[str, str] = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "redirect_uri": self.redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state_val,
            "access_type": access_type,
            "prompt": prompt,
        }
        if login_hint:
            params["login_hint"] = login_hint

        auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return auth_url, verifier, state_val

    def exchange_code_for_tokens(
        self,
        code: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        """Exchanges authorization code for Google access and refresh tokens."""
        self.validate_credentials()
        data: dict[str, str] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(GOOGLE_TOKEN_URL, data=data)
            resp.raise_for_status()
            tokens: dict[str, Any] = resp.json()
            tokens["created_at"] = time.time()
            return tokens

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refreshes an access token using a refresh token."""
        self.validate_credentials()
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(GOOGLE_TOKEN_URL, data=data)
            resp.raise_for_status()
            new_tokens: dict[str, Any] = resp.json()
            if "refresh_token" not in new_tokens:
                new_tokens["refresh_token"] = refresh_token
            new_tokens["created_at"] = time.time()
            return new_tokens

    def revoke_token(self, token: str) -> bool:
        """Revokes an active Google access or refresh token."""
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(GOOGLE_REVOKE_URL, params={"token": token})
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


# --- Vault Integration with Fernet Encryption ---


def save_tokens_to_vault(
    provider: str,
    user_id: str,
    tokens: dict[str, Any],
    vault: LocalSecureVault | None = None,
    sync_homelab_dev: bool = True,
) -> Path:
    """Encrypts and persists tokens in the local vault with Fernet symmetric encryption.

    Strictly separates storage by provider (least privilege):
    - google_calendar -> google_calendar_tokens_<user_id>.enc
    - google_gmail    -> google_gmail_tokens_<user_id>.enc
    """
    v = vault or get_vault()
    saved_path = v.store_tokens(provider=provider, user_id=user_id, tokens=tokens)

    # Optionally synchronize with runtime homelab dev container vault if directory exists
    if sync_homelab_dev:
        homelab_dev_vault = Path("/home/fsirio/homelab/biometric-coach-dev/data")
        if homelab_dev_vault.exists() and homelab_dev_vault.is_dir():
            try:
                v_dev = LocalSecureVault(vault_dir=homelab_dev_vault)
                v_dev.store_tokens(provider=provider, user_id=user_id, tokens=tokens)
                log.info(f"🔄 Synchronized encrypted tokens to homelab dev container vault for {provider}:{user_id}")
            except Exception as e:
                log.warning(f"Could not synchronize token to homelab dev vault: {e}")

    return saved_path


def load_tokens_from_vault(
    provider: str,
    user_id: str,
    vault: LocalSecureVault | None = None,
) -> dict[str, Any] | None:
    """Retrieves and decrypts tokens from LocalSecureVault."""
    v = vault or get_vault()
    tokens = v.retrieve_tokens(provider=provider, user_id=user_id)
    if not tokens:
        # Fallback check in homelab dev vault
        dev_vault = Path("/home/fsirio/homelab/biometric-coach-dev/data")
        if dev_vault.exists():
            with_dev = LocalSecureVault(vault_dir=dev_vault)
            tokens = with_dev.retrieve_tokens(provider=provider, user_id=user_id)
    return tokens


def get_valid_access_token(
    provider: str,
    user_id: str,
    vault: LocalSecureVault | None = None,
    oauth_client: GoogleOAuthClient | None = None,
) -> str:
    """Retrieves a valid access token, automatically refreshing and updating the vault if expired."""
    tokens = load_tokens_from_vault(provider=provider, user_id=user_id, vault=vault)
    if not tokens or not isinstance(tokens, dict):
        raise ValueError(
            f"No tokens found in vault for provider '{provider}' and user '{user_id}'. "
            f"Please run the authorization flow first."
        )

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    created_at = tokens.get("created_at", 0)

    # Check if expired or within 60s of expiration
    now = time.time()
    is_expired = (created_at + expires_in - 60) <= now if (created_at and expires_in) else False

    if is_expired and refresh_token:
        log.info(f"🔄 Access token for {provider}:{user_id} expired. Refreshing...")
        client = oauth_client or GoogleOAuthClient()
        new_tokens = client.refresh_access_token(refresh_token)
        save_tokens_to_vault(provider=provider, user_id=user_id, tokens=new_tokens, vault=vault)
        return str(new_tokens.get("access_token"))

    if not access_token:
        raise ValueError(f"No access_token found in stored credentials for {provider}:{user_id}.")

    return str(access_token)
