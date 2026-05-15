"""Script for manually refreshing Garmin authentication tokens."""

import logging
import sys

from src.utils.garmin_auth import refresh_garmin_tokens

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    """Refreshes Garmin tokens and exits with appropriate status code.

    Returns:
        None
    """
    log.info("Starting manual token refresh...")
    try:
        success: bool = refresh_garmin_tokens()
        if success:
            log.info("✅ Tokens refreshed successfully.")
            sys.exit(0)
        else:
            log.error("❌ Failed to refresh tokens.")
            sys.exit(1)
    except Exception as e:
        log.error(f"❌ An unexpected error occurred during refresh: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
