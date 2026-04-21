def retrieve_biometric_data() -> dict:
    """
    Mock function representing extraction from BigQuery/LanceDB based on data 
    provided by garmin-training-toolkit.
    """
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
