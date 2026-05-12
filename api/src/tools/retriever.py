import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

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
    start_date: str | None = Field(None, description="Start date for activity filtering (YYYY-MM-DD).")
    end_date: str | None = Field(None, description="End date for activity filtering (YYYY-MM-DD).")
    user_id: str | None = Field(None, description="The internal ID of the user (e.g., 'fsirio').")


import functools


# Cache for retrieve_biometric_data to avoid redundant BQ calls in short intervals
# TTL: 5 minutes (300 seconds)
def _get_cache_key(user_id):
    return f"{user_id}_{int(time.time() / 300)}"


@tool(args_schema=RetrieverInput)
def retrieve_biometric_data(
    project_id: str | None = None,
    dataset: str | None = None,
    limit: int = 20,
    offset: int = 0,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user_id: str | None = None,
) -> dict:
    """
    Retrieves the user's latest biometric context from BigQuery in parallel.
    Supports pagination and filtering for activities.
    """
    cache_key = _get_cache_key(user_id)
    return _retrieve_biometric_data_cached(
        project_id, dataset, limit, offset, activity_type, start_date, end_date, user_id, cache_key
    )


@functools.lru_cache(maxsize=32)
def _retrieve_biometric_data_cached(
    project_id, dataset, limit, offset, activity_type, start_date, end_date, user_id, cache_key
):
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

    # Common WHERE clause helper for user_id
    user_where = f"WHERE user_id = '{user_id}'" if user_id else ""

    def fetch_activities():
        nonlocal top_3_ids
        try:
            t0 = time.time()
            where_clauses = []
            if user_id:
                where_clauses.append(f"user_id = '{user_id}'")
            if activity_type:
                where_clauses.append(f"type = '{activity_type}'")

            # Helper to convert YYYY-MM-DD to nanoseconds
            def to_nanos(date_str):
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                return int(dt.timestamp() * 1e9)

            if start_date:
                where_clauses.append(f"date >= {to_nanos(start_date)}")
            if end_date:
                # Add 1 day to end_date to include the full day
                dt_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                end_nanos = int(dt_end.timestamp() * 1e9)
                where_clauses.append(f"date < {end_nanos}")

            where_clause = ""
            if where_clauses:
                where_clause = "WHERE " + " AND ".join(where_clauses)

            # Convert nanoseconds to TIMESTAMP for readable output
            query_act = f"""
                SELECT id, 
                       FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_MICROS(CAST(date / 1000 AS INT64))) as date, 
                       type, distance_m, avg_hr, vo2max 
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
            where_status = "WHERE (status IS NOT NULL OR acute_load IS NOT NULL)"
            if user_id:
                where_status += f" AND user_id = '{user_id}'"

            query_status = f"""
                SELECT status, acute_load, chronic_load, vo2max 
                FROM `{project_id}.{dataset}.training_status` 
                {where_status}
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
            where_sleep = "WHERE (duration_sec IS NOT NULL OR quality IS NOT NULL)"
            if user_id:
                where_sleep += f" AND user_id = '{user_id}'"

            query_sleep = f"""
                SELECT date, duration_sec, quality 
                FROM `{project_id}.{dataset}.sleep_history` 
                {where_sleep}
                ORDER BY date DESC LIMIT 1
            """
            sleep_rows = list(client.query(query_sleep).result())
            log.info(f"⏱️ BigQuery: Sleep history retrieved in {time.time() - t0:.2f}s")
            return "sleep", (dict(sleep_rows[0]) if sleep_rows else None)
        except Exception:
            return "sleep", None

    def fetch_hrv_history():
        try:
            t0 = time.time()
            query_hrv = f"""
                SELECT date, avg_hrv, min_hrv, max_hrv, status, baseline_low, baseline_high
                FROM `{project_id}.{dataset}.hrv_history`
                {user_where}
                ORDER BY date DESC LIMIT 7
            """
            hrv_rows = [dict(row) for row in client.query(query_hrv).result()]
            log.info(f"⏱️ BigQuery: HRV history retrieved in {time.time() - t0:.2f}s")
            return "hrv", hrv_rows
        except Exception:
            return "hrv", []

    def fetch_user_profile():
        try:
            t0 = time.time()
            query_profile = f"SELECT gender, age, height_cm, weight_kg, max_hr, resting_hr, custom_z1_max, custom_z2_max, custom_z3_max, custom_z4_max FROM `{project_id}.{dataset}.user_profile` {user_where} LIMIT 1"
            profile_rows = list(client.query(query_profile).result())
            log.info(f"⏱️ BigQuery: User profile retrieved in {time.time() - t0:.2f}s")
            return "user_profile", (dict(profile_rows[0]) if profile_rows else None)
        except Exception:
            return "user_profile", None

    def fetch_body_composition():
        try:
            t0 = time.time()
            query_body = f"SELECT date, weight_kg, bmi, fat_percentage, muscle_mass_kg FROM `{project_id}.{dataset}.body_composition` {user_where} ORDER BY date DESC LIMIT 1"
            body_rows = list(client.query(query_body).result())
            log.info(f"⏱️ BigQuery: Body composition retrieved in {time.time() - t0:.2f}s")
            return "latest_body_composition", (dict(body_rows[0]) if body_rows else None)
        except Exception:
            return "latest_body_composition", None

    def fetch_health_status():
        try:
            t0 = time.time()
            query_health = f"SELECT date, feeling, notes, fatigue_level, injury_notes FROM `{project_id}.{dataset}.user_health_status` {user_where} ORDER BY date DESC LIMIT 1"
            health_rows = list(client.query(query_health).result())
            log.info(f"⏱️ BigQuery: Health status retrieved in {time.time() - t0:.2f}s")
            return "latest_health_status", (dict(health_rows[0]) if health_rows else None)
        except Exception:
            return "latest_health_status", None

    def fetch_user_goals():
        try:
            t0 = time.time()
            user_filter = f" AND user_id = '{user_id}'" if user_id else ""
            query_goals = f"SELECT target_date, goal_type, target_value, description FROM `{project_id}.{dataset}.user_goals` WHERE status = 'active'{user_filter} ORDER BY target_date ASC"
            goal_rows = [dict(row) for row in client.query(query_goals).result()]
            log.info(f"⏱️ BigQuery: Active goals retrieved in {time.time() - t0:.2f}s")
            return "active_goals", goal_rows
        except Exception as e:
            log.warning(f"❌ Goals retrieval failed: {e}")
            return "active_goals", []

    def fetch_scheduled_workouts():
        try:
            t0 = time.time()
            # Fetch workouts from today onwards
            today = date.today().isoformat()
            where_sched = f"WHERE date >= '{today}'"
            if user_id:
                where_sched += f" AND user_id = '{user_id}'"

            query_sched = f"""
                SELECT title, date, sport_type, duration_sec, distance_m 
                FROM `{project_id}.{dataset}.scheduled_workouts` 
                {where_sched}
                ORDER BY date ASC 
                LIMIT 5
            """
            sched_rows = [dict(row) for row in client.query(query_sched).result()]
            log.info(f"⏱️ BigQuery: Scheduled workouts retrieved in {time.time() - t0:.2f}s")
            return "scheduled_workouts", sched_rows
        except Exception as e:
            log.warning(f"❌ Scheduled workouts retrieval failed: {e}")
            return "scheduled_workouts", []

    def fetch_telemetry(activity_ids):
        if not activity_ids:
            return "last_3_runs_timeseries_summary", "No detailed telemetry found."
        try:
            t0 = time.time()
            ids_str = ", ".join([f"'{i}'" for i in activity_ids])

            # Optimization: Add a date filter to the telemetry query to hit partitions
            # We assume telemetry for the last 3 activities is within the last 30 days.
            thirty_days_ago = int((datetime.now() - timedelta(days=30)).timestamp() * 1e6)

            # Implementation of Dynamic Effort Segmentation (from telemetry-optimization-plan.md)
            query_tel_series = f"""
            WITH raw_minutes AS (
                -- 1. Aggregate to 1-minute blocks for baseline smoothing
                SELECT 
                    activity_id,
                    activity_name,
                    TIMESTAMP_TRUNC(TIMESTAMP_MICROS(CAST(timestamp_ms * 1000 AS INT64)), MINUTE) as minute,
                    AVG(hr_bpm) as hr,
                    AVG(power_w) as pwr,
                    AVG(cadence_spm) as cad,
                    AVG(vertical_oscillation_cm) as osc,
                    AVG(ground_contact_time_ms) as gct
                FROM `{project_id}.{dataset}.latest_activity_telemetry`
                WHERE activity_id IN ({ids_str}) 
                  AND timestamp_ms >= {thirty_days_ago}
                  {f" AND user_id = '{user_id}'" if user_id else ""}
                GROUP BY 1, 2, 3
            ),
            deltas AS (
                -- 2. Calculate deltas to find "shifts" in effort
                SELECT 
                    activity_id, activity_name, minute, hr, pwr, cad, osc, gct,
                    LAG(hr) OVER(PARTITION BY activity_id ORDER BY minute) as prev_hr,
                    LAG(pwr) OVER(PARTITION BY activity_id ORDER BY minute) as prev_pwr
                FROM raw_minutes
            ),
            segments AS (
                -- 3. Mark the start of a new segment if HR or Power changes significantly
                SELECT 
                    activity_id, activity_name, minute, hr, pwr, cad, osc, gct,
                    CASE 
                        WHEN prev_hr IS NULL THEN 1
                        WHEN ABS(hr - prev_hr) > 7 OR ABS(pwr - prev_pwr) > 25 THEN 1 
                        ELSE 0 
                    END as is_new_segment
                FROM deltas
            ),
            segmented_data AS (
                -- 4. Assign segment IDs
                SELECT 
                    activity_id, activity_name, minute, hr, pwr, cad, osc, gct,
                    SUM(is_new_segment) OVER(PARTITION BY activity_id ORDER BY minute) as segment_id
                FROM segments
            )
            -- 5. Final aggregation of segments
            SELECT 
                activity_id,
                activity_name,
                MIN(minute) as start_time,
                COUNT(*) as duration_mins,
                AVG(hr) as avg_hr,
                AVG(pwr) as avg_pwr,
                AVG(cad) as avg_cad,
                AVG(osc) as avg_osc,
                AVG(gct) as avg_gct
            FROM segmented_data
            GROUP BY 1, 2, segment_id
            ORDER BY activity_id, start_time ASC
            """
            rows = list(client.query(query_tel_series).result())

            series_data: dict[str, list[str]] = {}
            for row in rows:
                key = f"{row.activity_name} (ID: {row.activity_id})"
                if key not in series_data:
                    series_data[key] = []

                metrics = [f"{int(row.duration_mins)}m", f"{int(row.avg_hr)}bpm"]
                if row.avg_pwr and row.avg_pwr > 0:
                    metrics.append(f"{int(row.avg_pwr)}W")
                if row.avg_osc:
                    metrics.append(f"{round(row.avg_osc, 1)}cm_osc")
                if row.avg_gct:
                    metrics.append(f"{int(row.avg_gct)}ms_gct")

                series_data[key].append(f"[{'|'.join(metrics)}]")

            compact_series = []
            for activity_label, segments_list in series_data.items():
                compact_series.append(f"{activity_label}: {' '.join(segments_list)}")

            log.info(
                f"⏱️ BigQuery: Telemetry dynamic segments retrieved in {time.time() - t0:.2f}s ({len(rows)} segments)"
            )
            return "last_3_runs_timeseries_summary", (
                "\n".join(compact_series) if compact_series else "No detailed telemetry found."
            )
        except Exception as e:
            log.error(f"❌ Telemetry retrieval failed: {e}")
            return "last_3_runs_timeseries_summary", f"Error retrieving telemetry: {e}"

    # Execute first queries in parallel
    with ThreadPoolExecutor(max_workers=7) as executor:
        # We need to run fetch_activities first or concurrently, but we need its result for telemetry
        # To maximize parallelism, we start 1-6.
        f_act = executor.submit(fetch_activities)
        f_status = executor.submit(fetch_training_status)
        f_sleep = executor.submit(fetch_sleep_history)
        f_hrv = executor.submit(fetch_hrv_history)
        f_profile = executor.submit(fetch_user_profile)
        f_body = executor.submit(fetch_body_composition)
        f_health = executor.submit(fetch_health_status)
        f_goals = executor.submit(fetch_user_goals)
        f_sched = executor.submit(fetch_scheduled_workouts)

        # Wait for activities to finish to start telemetry
        act_key, act_val = f_act.result()
        context[act_key] = act_val

        # Now start telemetry (can run while others are still finishing)
        f_telemetry = executor.submit(fetch_telemetry, top_3_ids)

        # Collect results from others
        for f in [f_status, f_sleep, f_hrv, f_profile, f_body, f_health, f_goals, f_sched, f_telemetry]:
            key, val = f.result()
            context[key] = val

    # Fill in info for missing fields so the Agent knows what's up
    if not context.get("recent_activities"):
        context["recent_activities"] = [{"info": "No activity history found in Data Lake."}]
    if not context.get("training_status"):
        context["training_status"] = {"info": "No training status available."}
    if not context.get("sleep"):
        context["sleep"] = {"info": "Sleep data not found (normal if watch not worn during sleep)."}
    if not context.get("hrv"):
        context["hrv"] = [{"info": "HRV baseline not yet established."}]

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
