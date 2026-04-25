import logging
from langchain_core.tools import tool
from src.tools.etl_job import run_etl

log = logging.getLogger(__name__)

@tool
def sync_biometric_data():
    """
    Triggers an incremental synchronization of biometric data from the provider (e.g., Garmin) to BigQuery.
    Use this if the user mentions they just finished a workout, if the data seems stale, 
    or if they explicitly ask to 'sync' or 'update' their data.
    """
    try:
        log.info("🔄 Agent-triggered ETL sync starting...")
        run_etl()
        return "Successfully synchronized biometric data from provider to BigQuery."
    except Exception as e:
        log.error(f"❌ ETL sync failed: {e}")
        return f"Error during synchronization: {e}"
