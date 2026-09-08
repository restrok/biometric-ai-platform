"""Biometric provider factory utility supporting Garmin and Fitbit."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from garmin_training_toolkit_sdk.core.garmin import GarminProvider
from garmin_training_toolkit_sdk.utils import find_token_file

from src.utils.config import get_secret

log = logging.getLogger(__name__)

_providers: dict[str, Any] = {}


def get_provider(
    user_id: str | None = None,
    force_reload: bool = False,
    refresh: bool = False,
) -> Any:
    """
    Returns the active biometric provider (Garmin or Fitbit),
    swapping based on user profile or WATCH_PROVIDER environment variable.
    """
    global _providers

    cache_key = user_id or "default"
    if cache_key in _providers and not force_reload:
        return _providers[cache_key]

    # Determine watch provider preference
    target_user = user_id or os.getenv("DEFAULT_USER_ID", "default_user")
    watch_provider = os.getenv("WATCH_PROVIDER", "garmin")
    try:
        from src.storage.factory import get_storage_engine

        profile = get_storage_engine().get_user_profile(target_user)
        if profile and profile.get("watch_provider"):
            watch_provider = profile["watch_provider"]
    except Exception as e:
        log.debug(f"Could not load watch provider from profile: {e}")

    if str(watch_provider).lower() in ("google_health", "google"):
        from fitbit_training_toolkit_sdk.core.google_health import GoogleHealthProvider
        from fitbit_training_toolkit_sdk.testing.mock import MockFitbitProvider

        google_token_file = Path.home() / ".google_health" / f"google_tokens_{user_id or 'default'}.json"
        if google_token_file.exists():
            provider = GoogleHealthProvider(token_path=google_token_file)
        else:
            log.info(f"No Google Health tokens found on disk for {user_id}, falling back to MockFitbitProvider for simulated testing.")
            provider = MockFitbitProvider()
        _providers[cache_key] = provider
        return provider

    if str(watch_provider).lower() == "fitbit":
        from fitbit_training_toolkit_sdk.core.fitbit import FitbitProvider
        from fitbit_training_toolkit_sdk.testing.mock import MockFitbitProvider

        fitbit_token_file = Path.home() / ".fitbit" / f"fitbit_tokens_{user_id or 'default'}.json"
        if fitbit_token_file.exists():
            provider = FitbitProvider(token_path=fitbit_token_file)
        else:
            log.info(f"No Fitbit tokens on disk for {user_id}, using MockFitbitProvider for testing.")
            provider = MockFitbitProvider()
        _providers[cache_key] = provider
        return provider

    # --- Garmin Provider Flow ---
    if user_id and refresh:
        from src.utils.garmin_auth import refresh_user_token

        try:
            refresh_user_token(user_id)
            force_reload = True
        except Exception as e:
            log.warning(f"Proactive refresh failed in factory for {user_id}: {e}")

    # 1. Try to load from Secret Manager
    secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
    secret_name = f"{secret_base_name}-{user_id}" if user_id else secret_base_name

    token_json = get_secret(secret_name)
    if token_json:
        try:
            tokens = json.loads(token_json)
            token_dir = Path.home() / ".garminconnect"
            token_dir.mkdir(parents=True, exist_ok=True)
            token_file = token_dir / f"garmin_tokens_{user_id or 'default'}.json"

            with open(token_file, "w") as f:
                json.dump(tokens, f, indent=4)

            log.info(f"Successfully synchronized Garmin tokens for {user_id or 'default'}")
            provider = GarminProvider(token_path=token_file)
            _providers[cache_key] = provider
            return provider
        except Exception as e:
            log.warning(f"Failed to load tokens from Secret Manager: {e}")

    # 2. Fallback to local token file
    if user_id:
        possible_paths = [
            Path.home() / ".garminconnect" / f"garmin_tokens_{user_id}.json",
            Path(__file__).parent.parent.parent / f"garmin_tokens_{user_id}.json",
        ]
        for path in possible_paths:
            if path.exists():
                log.info(f"Using local Garmin tokens for user: {user_id}")
                provider = GarminProvider(token_path=path)
                _providers[cache_key] = provider
                return provider

    found_token_file = find_token_file()
    if not found_token_file:
        raise Exception("Authentication token not found in Secret Manager or local file.")

    provider = GarminProvider(token_path=found_token_file)
    _providers[cache_key] = provider
    return provider
