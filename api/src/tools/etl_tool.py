import logging
import threading

from langchain_core.tools import tool

from src.tools.etl_job import run_etl

log = logging.getLogger(__name__)


@tool
def sync_biometric_data():
    """
    Triggers an incremental synchronization of biometric data from the provider (e.g., Garmin) to BigQuery.
    Use this if the user mentions they just finished a workout, if the data seems stale,
    or if they explicitly ask to 'sync' or 'update' their data.
    This process runs in the background.
    """
    try:
        log.info("🔄 Agent-triggered ETL sync starting in background...")

        # Run ETL in a separate thread to avoid blocking the AI Agent's response
        # This reduces latency from ~40s to <1s for the tool call
        thread = threading.Thread(target=run_etl, daemon=True)
        thread.start()

        return {
            "status": "Success",
            "message": "Synchronization started in the background. Updated data will be available in approximately 30-60 seconds.",
            "instructions_for_coach": "Inform the user that the sync is running and that I will use the current (cached) data for this response. Advise them that for the most up-to-date analysis, they should wait a minute before the next question.",
        }
    except Exception as e:
        log.error(f"❌ Background ETL trigger failed: {e}")
        return f"Error starting background synchronization: {e}"
