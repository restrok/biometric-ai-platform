from garmin_training_toolkit_sdk.core.garmin import GarminProvider
from garmin_training_toolkit_sdk.utils import find_token_file

_provider = None


def get_provider():
    """
    Returns the active biometric provider (currently hardcoded to Garmin,
    but easily swappable for future brands).
    """
    global _provider
    if _provider is not None:
        return _provider

    # In the future, this could read from a user setting: provider_name = get_user_config("provider")
    token_file = find_token_file()
    if not token_file:
        raise Exception("Authentication token not found for the primary provider.")

    _provider = GarminProvider(token_path=token_file)
    return _provider
