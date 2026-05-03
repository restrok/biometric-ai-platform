import json
import logging
import os

from garmin_training_toolkit_sdk.core.garmin import GarminProvider
from garmin_training_toolkit_sdk.utils import find_token_file

from src.utils.config import get_secret

log = logging.getLogger(__name__)

_provider = None


def get_provider():
    """
    Returns the active biometric provider (currently hardcoded to Garmin,
    but easily swappable for future brands).
    """
    global _provider
    if _provider is not None:
        return _provider

    # 1. Try to load from Secret Manager first using configurable name
    secret_name = os.getenv("GARMIN_TOKENS_SECRET_NAME", "garmin-tokens")
    token_json = get_secret(secret_name)
    if token_json:
        try:
            import tempfile
            from pathlib import Path

            tokens = json.loads(token_json)
            # The SDK currently expects a file path for tokens.
            # We create a temporary file that persists for the duration of the process.
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tf:
                json.dump(tokens, tf)
                temp_path = Path(tf.name)

            log.info(f"Successfully loaded Garmin tokens from Secret Manager into {temp_path}")
            _provider = GarminProvider(token_path=temp_path)
            return _provider
        except Exception as e:
            log.warning(f"Failed to load Garmin tokens from Secret Manager: {e}")

    # 2. Fallback to local token file
    token_file = find_token_file()
    if not token_file:
        raise Exception("Authentication token not found in Secret Manager or local file.")

    _provider = GarminProvider(token_path=token_file)
    return _provider
