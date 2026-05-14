import sys
import os
import logging

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from utils.garmin_auth import refresh_garmin_tokens

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    success = refresh_garmin_tokens()
    if success:
        print("Tokens refreshed successfully")
    else:
        print("Failed to refresh tokens")
        sys.exit(1)
