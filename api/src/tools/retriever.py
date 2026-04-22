from google.cloud import bigquery
import os
import logging
import pandas as pd

log = logging.getLogger(__name__)

TABLE_NAME = "recent_activities"

import time

def retrieve_biometric_data(project_id: str = "bio-intelligence-dev", dataset: str = "biometric_data_dev") -> dict:
    """
    Retrieves the user's latest biometric context from BigQuery.
    Handles missing tables or data gracefully.
    """
    start_total = time.time()
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and not os.getenv("GOOGLE_CLOUD_PROJECT"):
        return _get_mock_data()

    client = bigquery.Client(project=project_id)
    context = {}

    # 1. Fetch recent activities
    try:
        t0 = time.time()
        query_act = f"SELECT id, CAST(date AS STRING) as date, type, distance_m, avg_hr, vo2max FROM `{project_id}.{dataset}.recent_activities` ORDER BY date DESC LIMIT 5"
        act_rows = [dict(row) for row in client.query(query_act).result()]
        context["recent_activities"] = act_rows
        top_3_ids = [str(row['id']) for row in act_rows[:3] if row.get('id')]
        log.info(f"⏱️ BigQuery: Activities retrieved in {time.time()-t0:.2f}s ({len(act_rows)} rows)")
    except Exception as e:
        log.warning(f"❌ Activities retrieval failed: {e}")
        context["recent_activities"] = []
        top_3_ids = []

    # 2. Fetch latest training status
    try:
        t0 = time.time()
        query_status = f"SELECT status, acute_load, chronic_load, vo2max FROM `{project_id}.{dataset}.training_status` ORDER BY date DESC LIMIT 1"
        status_rows = list(client.query(query_status).result())
        context["training_status"] = dict(status_rows[0]) if status_rows else None
        log.info(f"⏱️ BigQuery: Training status retrieved in {time.time()-t0:.2f}s")
    except Exception:
        context["training_status"] = None

    # 3. Fetch latest sleep score
    try:
        t0 = time.time()
        query_sleep = f"SELECT date, duration_sec, quality FROM `{project_id}.{dataset}.sleep_history` ORDER BY date DESC LIMIT 1"
        sleep_rows = list(client.query(query_sleep).result())
        context["sleep"] = dict(sleep_rows[0]) if sleep_rows else None
        log.info(f"⏱️ BigQuery: Sleep history retrieved in {time.time()-t0:.2f}s")
    except Exception:
        context["sleep"] = None

    # 4. Fetch sampled telemetry (Time-Series)
    if top_3_ids:
        try:
            t0 = time.time()
            ids_str = ", ".join([f"'{i}'" for i in top_3_ids])
            query_tel_series = f"""
            SELECT activity_id, activity_name, hr_bpm
            FROM `{project_id}.{dataset}.latest_activity_telemetry`
            WHERE activity_id IN ({ids_str})
              AND MOD(timestamp_ms, 60000) < 2000 
            ORDER BY activity_id, timestamp_ms ASC
            """
            rows = list(client.query(query_tel_series).result())
            
            series_data = {}
            for row in rows:
                key = f"{row.activity_name} (ID: {row.activity_id})"
                if key not in series_data: series_data[key] = []
                series_data[key].append(str(int(row.hr_bpm)))
            
            compact_series = []
            for activity_label, bpm_list in series_data.items():
                compact_series.append(f"{activity_label}: {', '.join(bpm_list)}")
            
            context["last_3_runs_timeseries_summary"] = "\n".join(compact_series) if compact_series else "No detailed telemetry found."
            log.info(f"⏱️ BigQuery: Telemetry time-series retrieved in {time.time()-t0:.2f}s ({len(rows)} samples)")
        except Exception as e:
            log.error(f"❌ Telemetry retrieval failed: {e}")
            context["last_3_runs_timeseries_summary"] = "Error retrieving telemetry."
    
    log.info(f"✅ Total context retrieval time: {time.time()-start_total:.2f}s")
    return context

    # Fill in info for missing fields so the Agent knows what's up
    if not context.get("recent_activities"):
        context["recent_activities"] = [{"info": "No activity history found in Data Lake."}]
    if not context.get("training_status"):
        context["training_status"] = {"info": "No training status available."}
    if not context.get("sleep"):
        context["sleep"] = {"info": "Sleep data not found (normal if watch not worn during sleep)."}
    
    context["hrv"] = {"info": "HRV baseline not yet established."}

    return context

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
