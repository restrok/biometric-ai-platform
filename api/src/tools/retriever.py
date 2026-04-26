import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from google.cloud import bigquery

from src.utils.config import get_config

log = logging.getLogger(__name__)


def _ensure_env():
    """Ensures environment variables are loaded."""
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        from src.utils.config import setup_environment

        setup_environment()


_ensure_env()
config = get_config()

# Cache clients per project to reduce initialization overhead
_bq_clients = {}


def get_bq_client(project_id):
    global _bq_clients
    if project_id not in _bq_clients:
        _bq_clients[project_id] = bigquery.Client(project=project_id)
    return _bq_clients[project_id]


from langchain_core.tools import tool
from pydantic import BaseModel, Field


class RetrieverInput(BaseModel):
    project_id: str | None = Field(None, description="GCP Project ID")
    dataset: str | None = Field(None, description="BigQuery Dataset ID")
    limit: int = Field(20, description="Max number of activities to retrieve.")
    offset: int = Field(0, description="Number of activities to skip (for paging).")
    activity_type: str | None = Field(None, description="Filter by type (e.g. 'running', 'walking').")


@tool(args_schema=RetrieverInput)
def retrieve_biometric_data(
    project_id: str | None = None, 
    dataset: str | None = None,
    limit: int = 20,
    offset: int = 0,
    activity_type: str | None = None
) -> dict:
    """
    Retrieves the user's latest biometric context from BigQuery in parallel.
    Supports pagination and filtering for activities.
    """
    if not project_id:
        project_id = config["project_id"]
    if not dataset:
        dataset = config["dataset_id"]

    if not project_id:
        log.warning("GOOGLE_CLOUD_PROJECT not set. Biometric retrieval will fail if not using mock data.")

    start_total = time.time()
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and not os.getenv("GOOGLE_CLOUD_PROJECT"):
        return _get_mock_data()

    client = get_bq_client(project_id)
    context = {}
    top_3_ids = []

    def fetch_activities():
        nonlocal top_3_ids
        try:
            t0 = time.time()
            where_clause = ""
            if activity_type:
                where_clause = f"WHERE type = '{activity_type}'"
            
            query_act = f"""
                SELECT id, CAST(date AS STRING) as date, type, distance_m, avg_hr, vo2max 
                FROM `{project_id}.{dataset}.recent_activities` 
                {where_clause}
                ORDER BY date DESC 
                LIMIT {limit} OFFSET {offset}
            """
            act_rows = [dict(row) for row in client.query(query_act).result()]
            top_3_ids = [str(row["id"]) for row in act_rows[:3] if row.get("id")]
            log.info(f"⏱️ BigQuery: Activities retrieved in {time.time() - t0:.2f}s ({len(act_rows)} rows)")
            return "recent_activities", act_rows
        except Exception as e:
            log.warning(f"❌ Activities retrieval failed: {e}")
            return "recent_activities", []

    def fetch_training_status():
        try:
            t0 = time.time()
            # Filter for records that actually have a status or load
            query_status = f"""
                SELECT status, acute_load, chronic_load, vo2max 
                FROM `{project_id}.{dataset}.training_status` 
                WHERE status IS NOT NULL OR acute_load IS NOT NULL
                ORDER BY date DESC LIMIT 1
            """
            status_rows = list(client.query(query_status).result())
            log.info(f"⏱️ BigQuery: Training status retrieved in {time.time() - t0:.2f}s")
            return "training_status", (dict(status_rows[0]) if status_rows else None)
        except Exception:
            return "training_status", None

    def fetch_sleep_history():
        try:
            t0 = time.time()
            # Filter for records that actually have a duration or quality
            query_sleep = f"""
                SELECT date, duration_sec, quality 
                FROM `{project_id}.{dataset}.sleep_history` 
                WHERE duration_sec IS NOT NULL OR quality IS NOT NULL
                ORDER BY date DESC LIMIT 1
            """
            sleep_rows = list(client.query(query_sleep).result())
            log.info(f"⏱️ BigQuery: Sleep history retrieved in {time.time() - t0:.2f}s")
            return "sleep", (dict(sleep_rows[0]) if sleep_rows else None)
        except Exception:
            return "sleep", None

    def fetch_user_profile():
        try:
            t0 = time.time()
            query_profile = f"SELECT gender, age, height_cm, weight_kg, max_hr, resting_hr, custom_z1_max, custom_z2_max, custom_z3_max, custom_z4_max FROM `{project_id}.{dataset}.user_profile` LIMIT 1"
            profile_rows = list(client.query(query_profile).result())
            log.info(f"⏱️ BigQuery: User profile retrieved in {time.time() - t0:.2f}s")
            return "user_profile", (dict(profile_rows[0]) if profile_rows else None)
        except Exception:
            return "user_profile", None

    def fetch_body_composition():
        try:
            t0 = time.time()
            query_body = f"SELECT date, weight_kg, bmi, fat_percentage, muscle_mass_kg FROM `{project_id}.{dataset}.body_composition` ORDER BY date DESC LIMIT 1"
            body_rows = list(client.query(query_body).result())
            log.info(f"⏱️ BigQuery: Body composition retrieved in {time.time() - t0:.2f}s")
            return "latest_body_composition", (dict(body_rows[0]) if body_rows else None)
        except Exception:
            return "latest_body_composition", None

    def fetch_telemetry(activity_ids):
        if not activity_ids:
            return "last_3_runs_timeseries_summary", "No detailed telemetry found."
        try:
            t0 = time.time()
            ids_str = ", ".join([f"'{i}'" for i in activity_ids])
            query_tel_series = f"""
            SELECT 
                activity_id, 
                activity_name, 
                hr_bpm, 
                power_w, 
                cadence_spm,
                stride_length_mm,
                vertical_oscillation_cm,
                ground_contact_time_ms,
                temperature_c
            FROM `{project_id}.{dataset}.latest_activity_telemetry`
            WHERE activity_id IN ({ids_str})
              AND MOD(timestamp_ms, 60000) < 2000 
            ORDER BY activity_id, timestamp_ms ASC
            """
            rows = list(client.query(query_tel_series).result())

            series_data: dict[str, list[str]] = {}
            for row in rows:
                key = f"{row.activity_name} (ID: {row.activity_id})"
                if key not in series_data:
                    series_data[key] = []

                metrics = [f"{int(row.hr_bpm)}bpm"]
                if row.get("power_w"):
                    metrics.append(f"{int(row.power_w)}W")
                if row.get("vertical_oscillation_cm"):
                    metrics.append(f"{round(row.vertical_oscillation_cm, 1)}cm_osc")
                if row.get("ground_contact_time_ms"):
                    metrics.append(f"{int(row.ground_contact_time_ms)}ms_gct")

                series_data[key].append(f"[{'|'.join(metrics)}]")

            compact_series = []
            for activity_label, bpm_list in series_data.items():
                compact_series.append(f"{activity_label}: {', '.join(bpm_list)}")

            log.info(f"⏱️ BigQuery: Telemetry time-series retrieved in {time.time() - t0:.2f}s ({len(rows)} samples)")
            return "last_3_runs_timeseries_summary", (
                "\n".join(compact_series) if compact_series else "No detailed telemetry found."
            )
        except Exception as e:
            log.error(f"❌ Telemetry retrieval failed: {e}")
            return "last_3_runs_timeseries_summary", "Error retrieving telemetry."

    # Execute first 5 queries in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        # We need to run fetch_activities first or concurrently, but we need its result for telemetry
        # To maximize parallelism, we start 1-5.
        f_act = executor.submit(fetch_activities)
        f_status = executor.submit(fetch_training_status)
        f_sleep = executor.submit(fetch_sleep_history)
        f_profile = executor.submit(fetch_user_profile)
        f_body = executor.submit(fetch_body_composition)

        # Wait for activities to finish to start telemetry
        act_key, act_val = f_act.result()
        context[act_key] = act_val

        # Now start telemetry (can run while others are still finishing)
        f_telemetry = executor.submit(fetch_telemetry, top_3_ids)

        # Collect results from others
        for f in [f_status, f_sleep, f_profile, f_body, f_telemetry]:
            key, val = f.result()
            context[key] = val

    # Fill in info for missing fields so the Agent knows what's up
    if not context.get("recent_activities"):
        context["recent_activities"] = [{"info": "No activity history found in Data Lake."}]
    if not context.get("training_status"):
        context["training_status"] = {"info": "No training status available."}
    if not context.get("sleep"):
        context["sleep"] = {"info": "Sleep data not found (normal if watch not worn during sleep)."}

    context["hrv"] = {"info": "HRV baseline not yet established."}

    log.info(f"✅ Total context retrieval time: {time.time() - start_total:.2f}s")

    # Final deep serialization for JSON compliance
    def serialize_dates(obj):
        if isinstance(obj, dict):
            return {k: serialize_dates(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize_dates(i) for i in obj]
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return obj

    return serialize_dates(context)


def _get_mock_data() -> dict:
    return {
        "recent_activities": [
            {"date": "2024-10-01", "type": "running", "distance_km": 10.5, "avg_hr": 145, "zone": "Z3"},
            {"date": "2024-10-03", "type": "running", "distance_km": 5.0, "avg_hr": 125, "zone": "Z2"},
        ],
        "readiness": {"sleep_score": 58, "hrv_status": "unbalanced", "recovery_time_hours": 36},
    }
