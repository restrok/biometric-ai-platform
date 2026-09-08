"""Security and multi-tenant authentication dependencies for FastAPI."""

import logging
import os

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.storage.factory import get_storage_engine

log = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_current_user(
    x_api_key: str | None = Security(API_KEY_HEADER),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> str:
    """Validates the API Key and resolves the authorized tenant user_id.

    Behavior:
    1. If AUTH_DISABLED is 'true', falls back to x_user_id or DEFAULT_USER_ID.
    2. Otherwise, validates x_api_key against the configured StorageEngine.
    """
    auth_disabled = os.getenv("AUTH_DISABLED", "false").lower() in ("true", "1", "yes")
    default_user = os.getenv("DEFAULT_USER_ID", "default_user")

    effective_user_id = (x_user_id or default_user).strip()

    if auth_disabled:
        return effective_user_id

    # If master API key configured in env matches
    master_key = os.getenv("BIOMETRIC_API_KEY")
    if master_key and x_api_key == master_key:
        return effective_user_id

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required 'X-API-Key' header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    engine = get_storage_engine()
    is_valid = engine.validate_api_key(x_api_key, effective_user_id)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid API Key for user '{effective_user_id}'.",
        )

    return effective_user_id
