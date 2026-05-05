import json
import logging
import os

from garmin_training_toolkit_sdk.core.garmin import GarminProvider
from garmin_training_toolkit_sdk.utils import find_token_file

from src.utils.config import get_secret

log = logging.getLogger(__name__)

_providers: dict[str, GarminProvider] = {}


def get_provider(user_id: str | None = None):
    """
    Returns the active biometric provider (currently hardcoded to Garmin,
    but easily swappable for future brands).
    
    If user_id is provided, it attempts to load user-specific tokens.
    """
    global _providers
    
    cache_key = user_id or "default"
    if cache_key in _providers:
        return _providers[cache_key]

    # 1. Try to load from Secret Manager first using configurable name
    # Defaulting to garmin-tokens for single-user, or garmin-tokens-{user_id} for multi-user
    secret_base_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
    secret_name = f"{secret_base_name}-{user_id}" if user_id else secret_base_name
    
    token_json = get_secret(secret_name)
    if token_json:
        try:
            import tempfile
            from pathlib import Path

            tokens = json.loads(token_json)
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tf:
                json.dump(tokens, tf)
                temp_path = Path(tf.name)

            log.info(f"Successfully loaded Garmin tokens for {user_id or 'default'} from Secret Manager")
            provider = GarminProvider(token_path=temp_path)
            _providers[cache_key] = provider
            return provider
        except Exception as e:
            log.warning(f"Failed to load tokens from Secret Manager: {e}")

    # 2. Fallback to local token file
    # We look for garmin_tokens_{user_id}.json or the default from the SDK
    if user_id:
        from pathlib import Path
        # Search in common locations with the user suffix
        possible_paths = [
            Path.home() / ".garminconnect" / f"garmin_tokens_{user_id}.json",
            Path(__file__).parent.parent.parent / f"garmin_tokens_{user_id}.json",
        ]
        for path in possible_paths:
            if path.exists():
                log.info(f"Using local tokens for user: {user_id}")
                provider = GarminProvider(token_path=path)
                _providers[cache_key] = provider
                return provider

    token_file = find_token_file()
    if not token_file:
        raise Exception("Authentication token not found in Secret Manager or local file.")

    provider = GarminProvider(token_path=token_file)
    _providers[cache_key] = provider
    return provider
