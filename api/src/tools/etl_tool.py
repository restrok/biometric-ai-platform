import logging

from langchain_core.tools import tool

from src.tools.etl_job import run_etl

from src.tools.retriever import retrieve_biometric_data

log = logging.getLogger(__name__)


@tool
def sync_biometric_data():
    """
    Triggers an incremental synchronization of biometric data from the provider (e.g., Garmin) to BigQuery.
    Use this if the user mentions they just finished a workout, if the data seems stale,
    or if they explicitly ask to 'sync' or 'update' their data.
    After successful sync, it automatically retrieves and returns the most updated context.
    """
    try:
        log.info("🔄 Agent-triggered ETL sync starting...")
        run_etl()
        
        log.info("📡 ETL complete. Refreshing local context for the Agent...")
        updated_context = retrieve_biometric_data.invoke({})
        
        return {
            "status": "Successfully synchronized biometric data from provider to BigQuery.",
            "updated_biometric_context": updated_context
        }
    except Exception as e:
        log.error(f"❌ ETL sync failed: {e}")
        return f"Error during synchronization: {e}"
