"""One-time backfill for a year of daily physiology data."""

import logging
import time
from datetime import datetime, timedelta

import pandas as pd

from src.tools.etl_job import get_daily_physiology, upsert_to_bq
from src.utils.config import setup_environment
from src.utils.provider_factory import get_provider

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)


def run_backfill():
    setup_environment()
    user_id = "fsirio"
    log.info(f"🚀 Starting 1-year daily physiology backfill for {user_id}...")

    provider = get_provider(user_id=user_id, refresh=True)
    client = getattr(provider, "client", None)
    if not client:
        log.error("Failed to authenticate Garmin client.")
        return

    # Set display name for wellness endpoints
    if not client.display_name:
        try:
            settings = client.get_userprofile_settings()
            client.display_name = settings.get("displayName")
        except Exception as e:
            log.error(f"Could not retrieve display_name: {e}")
            return

    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)

    # Process in 30-day chunks to be safe
    chunk_size = 30
    current_end = end_date

    total_synced = 0

    while current_end > start_date:
        current_start = max(start_date, current_end - timedelta(days=chunk_size))

        start_str = current_start.strftime("%Y-%m-%d")
        end_str = current_end.strftime("%Y-%m-%d")

        log.info(f"📅 Fetching chunk: {start_str} to {end_str}...")

        try:
            daily_phys = get_daily_physiology(client, start_str, end_str)
            if daily_phys:
                df_daily = pd.DataFrame(daily_phys)
                upsert_to_bq(df_daily, "daily_physiology", unique_key="date", user_id=user_id)
                total_synced += len(daily_phys)
                log.info(f"✅ Synced {len(daily_phys)} days in this chunk.")
            else:
                log.warning(f"⚠️ No data found for chunk {start_str} to {end_str}.")
        except Exception as e:
            log.error(f"❌ Chunk failed: {e}")

        # Rate limiting: Sleep between chunks
        log.info("😴 Resting for 5 seconds to prevent rate limits...")
        time.sleep(5)

        current_end = current_start - timedelta(days=1)

    log.info(f"🏁 Backfill complete! Total days synced: {total_synced}")


if __name__ == "__main__":
    run_backfill()
