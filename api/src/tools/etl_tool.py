import logging
import threading

from langchain_core.tools import tool

from src.tools.etl_job import run_etl

log = logging.getLogger(__name__)


@tool
def sync_biometric_data(
    user_id: str | None = None,
    days_back: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    Triggers a synchronization of biometric data from the provider (e.g., Garmin) to BigQuery.
    Use this if the user mentions they just finished a workout, if data seems stale,
    or if they explicitly ask to 'sync' or 'update'.

    Args:
        user_id: Internal ID of the user (defaults to 'fsirio').
        days_back: Number of days to look back (safety default is applied in the engine).
        start_date: Explicit start date (YYYY-MM-DD).
        end_date: Explicit end date (YYYY-MM-DD).
    """
    try:
        log.info(f"🔄 Agent-triggered ETL sync starting in background for user: {user_id}...")

        # Run ETL in a separate thread to avoid blocking the AI Agent's response
        sync_args = {
            "user_id": user_id,
            "days_back": days_back,
            "start_date": start_date,
            "end_date": end_date,
        }
        thread = threading.Thread(target=run_etl, kwargs=sync_args, daemon=True)
        thread.start()

        return {
            "status": "Success",
            "message": "Synchronization started in the background. Updated data will be available in approximately 30-60 seconds.",
            "instructions_for_coach": "Inform the user that the sync is running. If no specific range was provided, I am using a safety-capped incremental sync.",
        }
    except Exception as e:
        log.error(f"❌ Background ETL trigger failed: {e}")
        return f"Error starting background synchronization: {e}"
