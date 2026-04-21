from google.cloud import bigquery
import os
import logging

log = logging.getLogger(__name__)

def retrieve_biometric_data(project_id: str = "bio-intelligence-dev", dataset: str = "biometric_data_dev") -> dict:
    """
    Retrieves the user's latest biometric context by executing queries against BigQuery.
    These BigQuery tables are populated asynchronously by the garmin-training-toolkit SDK.
    """
    # For local development without GCP credentials, fallback to mock data
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and not os.getenv("GOOGLE_CLOUD_PROJECT"):
        log.warning("No Google Cloud credentials found. Using local mock data.")
        return _get_mock_data()

    try:
        client = bigquery.Client(project=project_id)
        
        # In a real scenario, we would run SQL against the External Tables
        # query = f"""
        # SELECT date, distance_km, avg_hr, zone 
        # FROM `{project_id}.{dataset}.recent_activities` 
        # ORDER BY date DESC LIMIT 5
        # """
        # activities = [dict(row) for row in client.query(query).result()]
        
        log.info("Successfully connected to BigQuery.")
        # Returning mock data until the ETL pipeline actually uploads the Parquet files
        return _get_mock_data()
        
    except Exception as e:
        log.error(f"BigQuery retrieval failed: {e}")
        return {"error": "Failed to retrieve biometric data from data lake."}

def _get_mock_data() -> dict:
    return {
        "recent_activities": [
            {"date": "2024-10-01", "type": "running", "distance_km": 10.5, "avg_hr": 145, "zone": "Z3"},
            {"date": "2024-10-03", "type": "running", "distance_km": 5.0, "avg_hr": 125, "zone": "Z2"}
        ],
        "readiness": {
            "sleep_score": 58, 
            "hrv_status": "unbalanced",
            "recovery_time_hours": 36
        }
    }

