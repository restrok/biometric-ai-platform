"""Tools for retrieving biometric data from BigQuery."""

import functools
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

# Configure logging
log = logging.getLogger(__name__)


def _ensure_env() -> None:
    """Ensures environment variables are loaded."""
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        from src.utils.config import setup_environment

        setup_environment()


_ensure_env()
config = get_config()

# Cache clients per project to reduce initialization overhead
_bq_clients: dict[str, bigquery.Client] = {}


def get_bq_client(project_id: str) -> bigquery.Client:
    """Gets or creates a BigQuery client for the given project ID.

    Args:
        project_id: The GCP Project ID.

    Returns:
        A BigQuery client instance.
    """
    global _bq_clients
    if project_id not in _bq_clients:
        _bq_clients[project_id] = bigquery.Client(project=project_id)
    return _bq_clients[project_id]


class RetrieverInput(BaseModel):
    """Input schema for the biometric data retriever tool."""

    project_id: str | None = Field(None, description="GCP Project ID")
    dataset: str | None = Field(None, description="BigQuery Dataset ID")
    limit: int = Field(20, description="Max number of activities to retrieve.")
    offset: int = Field(0, description="Number of activities to skip (for paging).")
    activity_type: str | None = Field(None, description="Filter by type (e.g. 'running', 'walking').")
    start_date: str | None = Field(None, description="Start date for activity filtering (YYYY-MM-DD).")
    end_date: str | None = Field(None, description="End date for activity filtering (YYYY-MM-DD).")
    user_id: str | None = Field(None, description="The internal ID of the user (e.g., 'fsirio').")


def _get_cache_key(user_id: str | None) -> str:
    """Generates a cache key for retrieve_biometric_data.

    TTL is approximately 5 minutes (300 seconds).

    Args:
        user_id: The internal ID of the user.

    Returns:
        A string representing the cache key.
    """
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
) -> dict[str, Any]:
    """Retrieves the user's latest biometric context from BigQuery in parallel.

    Supports pagination and filtering for activities.

    Args:
        project_id: GCP Project ID.
        dataset: BigQuery Dataset ID.
        limit: Max number of activities to retrieve.
        offset: Number of activities to skip.
        activity_type: Filter by activity type.
        start_date: Start date for filtering (YYYY-MM-DD).
        end_date: End date for filtering (YYYY-MM-DD).
        user_id: Internal user ID.

    Returns:
        A dictionary containing the user's biometric context.
    """
    cache_key = _get_cache_key(user_id)
    return _retrieve_biometric_data_cached(
        project_id,
        dataset,
        limit,
        offset,
        activity_type,
        start_date,
        end_date,
        user_id,
        cache_key,
    )


@functools.lru_cache(maxsize=32)
def _retrieve_biometric_data_cached(
    project_id: str | None,
    dataset: str | None,
    limit: int,
    offset: int,
    activity_type: str | None,
    start_date: str | None,
    end_date: str | None,
    user_id: str | None,
    cache_key: str,
) -> dict[str, Any]:
    """Cached implementation of biometric data retrieval.

    Args:
        project_id: GCP Project ID.
        dataset: BigQuery Dataset ID.
        limit: Max number of activities to retrieve.
        offset: Number of activities to skip.
        activity_type: Filter by activity type.
        start_date: Start date for filtering (YYYY-MM-DD).
        end_date: End date for filtering (YYYY-MM-DD).
        user_id: Internal user ID.
        cache_key: Unique cache key (includes TTL).

    Returns:
        A dictionary containing the user's biometric context.
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
    context: dict[str, Any] = {}
    top_3_ids: list[str] = []

    # STRICT USER ISOLATION: Default to 'fsirio' if not provided for safety
    user_id = user_id or "fsirio"
    user_where = f"WHERE user_id = '{user_id}'"

    def fetch_activities() -> tuple[str, list[dict[str, Any]]]:
        """Fetches recent activities from BigQuery."""
        nonlocal top_3_ids
        try:
            t0 = time.time()
            where_clauses = [f"user_id = '{user_id}'"]
            if activity_type:
                where_clauses.append(f"type = '{activity_type}'")

            def to_unix_seconds(date_str: str) -> int:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                return int(dt.timestamp())

            if start_date:
                where_clauses.append(f"date >= {to_unix_seconds(start_date)}")
            if end_date:
                dt_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                end_seconds = int(dt_end.timestamp())
                where_clauses.append(f"date < {end_seconds}")

            where_clause = "WHERE " + " AND ".join(where_clauses)

            query_act = f"""
                SELECT id, 
                       FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_SECONDS(CAST(date AS INT64))) as date, 
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

    def fetch_training_status() -> tuple[str, dict[str, Any] | None]:
        """Fetches the latest training status."""
        try:
            t0 = time.time()
            query_status = f"""
                SELECT status, acute_load, training_load_balance, vo2max_precise, 
                       primary_benefit, recovery_time_hours
                FROM `{project_id}.{dataset}.training_status` 
                {user_where}
                ORDER BY date DESC LIMIT 1
            """
            status_rows = list(client.query(query_status).result())
            log.info(f"⏱️ BigQuery: Training status retrieved in {time.time() - t0:.2f}s")
            return "training_status", (dict(status_rows[0]) if status_rows else None)
        except Exception:
            return "training_status", None

    def fetch_sleep_history() -> tuple[str, dict[str, Any] | None]:
        """Fetches the latest sleep record."""
        try:
            t0 = time.time()
            query_sleep = f"""
                SELECT date, duration_sec, quality, deep_sec, light_sec, 
                       rem_sec, awake_sec
                FROM `{project_id}.{dataset}.sleep_history` 
                {user_where}
                ORDER BY date DESC LIMIT 1
            """
            sleep_rows = list(client.query(query_sleep).result())
            log.info(f"⏱️ BigQuery: Sleep history retrieved in {time.time() - t0:.2f}s")
            return "sleep", (dict(sleep_rows[0]) if sleep_rows else None)
        except Exception:
            return "sleep", None

    def fetch_hrv_history() -> tuple[str, list[dict[str, Any]]]:
        """Fetches recent HRV history."""
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

    def fetch_user_profile() -> tuple[str, dict[str, Any] | None]:
        """Fetches user profile information."""
        try:
            t0 = time.time()
            query_profile = (
                f"SELECT gender, age, height_cm, weight_kg, max_hr, resting_hr, "
                f"custom_z1_max, custom_z2_max, custom_z3_max, custom_z4_max "
                f"FROM `{project_id}.{dataset}.user_profile` {user_where} LIMIT 1"
            )
            profile_rows = list(client.query(query_profile).result())
            log.info(f"⏱️ BigQuery: User profile retrieved in {time.time() - t0:.2f}s")
            return "user_profile", (dict(profile_rows[0]) if profile_rows else None)
        except Exception:
            return "user_profile", None

    def fetch_body_composition() -> tuple[str, dict[str, Any] | None]:
        """Fetches the latest body composition data."""
        try:
            t0 = time.time()
            query_body = (
                f"SELECT date, weight_kg, bmi, fat_percentage, muscle_mass_kg "
                f"FROM `{project_id}.{dataset}.body_composition` {user_where} "
                f"ORDER BY date DESC LIMIT 1"
            )
            body_rows = list(client.query(query_body).result())
            log.info(f"⏱️ BigQuery: Body composition retrieved in {time.time() - t0:.2f}s")
            return "latest_body_composition", (dict(body_rows[0]) if body_rows else None)
        except Exception:
            return "latest_body_composition", None

    def fetch_health_status() -> tuple[str, dict[str, Any] | None]:
        """Fetches the latest health status from the last 3 days."""
        t0 = time.time()
        try:
            where_clauses = ["date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)"]
            if user_id:
                where_clauses.append(f"user_id = '{user_id}'")

            where_str = "WHERE " + " AND ".join(where_clauses)

            query_health = f"""
                SELECT date, feeling, notes, fatigue_level, injury_notes
                FROM `{project_id}.{dataset}.user_health_status`
                {where_str}
                ORDER BY date DESC LIMIT 1
            """

            health_rows = list(client.query(query_health).result())
            log.info(f"⏱️ BigQuery: Health status retrieved in {time.time() - t0:.2f}s")
            return "latest_health_status", (dict(health_rows[0]) if health_rows else None)
        except Exception as e:
            log.warning(f"❌ Health status retrieval failed: {e}")
            return "latest_health_status", None

    def fetch_user_goals() -> tuple[str, list[dict[str, Any]]]:
        """Fetches active user goals."""
        try:
            t0 = time.time()
            user_filter = f" AND user_id = '{user_id}'" if user_id else ""
            query_goals = (
                f"SELECT target_date, goal_type, target_value, description "
                f"FROM `{project_id}.{dataset}.user_goals` "
                f"WHERE status = 'active'{user_filter} ORDER BY target_date ASC"
            )
            goal_rows = [dict(row) for row in client.query(query_goals).result()]
            log.info(f"⏱️ BigQuery: Active goals retrieved in {time.time() - t0:.2f}s")
            return "active_goals", goal_rows
        except Exception as e:
            log.warning(f"❌ Goals retrieval failed: {e}")
            return "active_goals", []

    def fetch_daily_physiology() -> tuple[str, list[dict[str, Any]]]:
        """Fetches recent daily physiology (RHR, Stress, Body Battery)."""
        try:
            t0 = time.time()
            query_daily = f"""
                SELECT date, resting_heart_rate, all_day_stress_avg, body_battery_end_of_day, total_steps
                FROM `{project_id}.{dataset}.daily_physiology` 
                {user_where}
                ORDER BY date DESC LIMIT 7
            """
            daily_rows = [dict(row) for row in client.query(query_daily).result()]
            log.info(f"⏱️ BigQuery: Daily physiology retrieved in {time.time() - t0:.2f}s")
            return "daily_physiology_7d", daily_rows
        except Exception:
            return "daily_physiology_7d", []

    def fetch_calibration_profile() -> tuple[str, list[dict[str, Any]]]:
        """Fetches personal calibration markers (PCP)."""
        try:
            t0 = time.time()
            query_calib = f"""
                SELECT marker_type, marker_value, context
                FROM `{project_id}.{dataset}.user_calibration_profile` 
                {user_where}
            """
            calib_rows = [dict(row) for row in client.query(query_calib).result()]
            log.info(f"⏱️ BigQuery: Calibration profile retrieved in {time.time() - t0:.2f}s")
            return "personal_calibration_profile", calib_rows
        except Exception:
            return "personal_calibration_profile", []

    def fetch_scheduled_workouts() -> tuple[str, list[dict[str, Any]]]:
        """Fetches scheduled workouts from today onwards."""
        try:
            t0 = time.time()
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

    def fetch_telemetry(activity_ids: list[str]) -> tuple[str, str]:
        """Fetches and aggregates telemetry for the last 3 activities."""
        if not activity_ids:
            return "last_3_runs_timeseries_summary", "No detailed telemetry found."
        try:
            t0 = time.time()
            ids_str = ", ".join([f"'{i}'" for i in activity_ids])
            thirty_days_ago_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

            # Implementation of Event-Based Aggregation (V3 - Unabridged)
            query_tel_series = f"""
            WITH raw_15s AS (
                SELECT 
                    activity_id,
                    activity_name,
                    TIMESTAMP_SECONDS(CAST(FLOOR(timestamp_ms / 15000) * 15 AS INT64)) as time_block,
                    AVG(hr_bpm) as hr,
                    MAX(hr_bpm) as max_hr,
                    AVG(power_w) as pwr,
                    MAX(power_w) as max_pwr,
                    AVG(cadence_spm + IFNULL(fractional_cadence, 0)) as cad,
                    AVG(stride_length_mm) as stride,
                    AVG(vertical_oscillation_cm) as osc,
                    AVG(ground_contact_time_ms) as gct,
                    AVG(vertical_ratio) as v_ratio,
                    AVG(vertical_speed) as v_speed,
                    AVG(body_battery) as battery,
                    AVG(temperature_c) as temp,
                    AVG(elevation_m) as elev,
                    AVG(speed_mps) as speed,
                    AVG(gap_mps) as gap,
                    AVG(performance_condition) as perf,
                    AVG(run_walk_index) as rw_idx
                FROM `{project_id}.{dataset}.latest_activity_telemetry`
                WHERE activity_id IN ({ids_str}) 
                  AND timestamp_ms >= {thirty_days_ago_ms}
                  {f" AND user_id = '{user_id}'" if user_id else ""}
                GROUP BY 1, 2, 3
            ),
            classified AS (
                SELECT 
                    activity_id, activity_name, time_block, hr, max_hr, pwr, max_pwr, cad, 
                    stride, osc, gct, v_ratio, v_speed, battery, temp, elev, speed, gap, perf, rw_idx,
                    CASE WHEN pwr > 180 OR cad > 145 THEN 1 ELSE 0 END as is_work,
                    CAST(FLOOR(UNIX_SECONDS(time_block) / 300) AS INT64) as time_bucket
                FROM raw_15s
            ),
            state_changes AS (
                SELECT 
                    activity_id, activity_name, time_block, hr, max_hr, pwr, max_pwr, cad, 
                    stride, osc, gct, v_ratio, v_speed, battery, temp, elev, speed, gap, perf, rw_idx,
                    is_work, time_bucket,
                    CASE 
                        WHEN is_work != LAG(is_work) OVER(PARTITION BY activity_id ORDER BY time_block) THEN 1 
                        WHEN time_bucket != LAG(time_bucket) OVER(PARTITION BY activity_id ORDER BY time_block) THEN 1
                        ELSE 0 
                    END as state_change
                FROM classified
            ),
            segments AS (
                SELECT 
                    activity_id, activity_name, time_block, hr, max_hr, pwr, max_pwr, cad, 
                    stride, osc, gct, v_ratio, v_speed, battery, temp, elev, speed, gap, perf, rw_idx,
                    is_work,
                    SUM(state_change) OVER(PARTITION BY activity_id ORDER BY time_block) as segment_id
                FROM state_changes
            )
            SELECT 
                activity_id, activity_name, is_work,
                MIN(time_block) as start_time,
                COUNT(*) * 15 as duration_sec,
                AVG(hr) as avg_hr, MAX(max_hr) as max_hr,
                AVG(pwr) as avg_pwr, MAX(max_pwr) as max_pwr,
                AVG(cad) as avg_cad,
                AVG(stride) as avg_stride,
                AVG(osc) as avg_osc,
                AVG(gct) as avg_gct,
                AVG(v_ratio) as avg_v_ratio,
                AVG(v_speed) as avg_v_speed,
                AVG(battery) as avg_battery,
                AVG(temp) as avg_temp,
                AVG(elev) as avg_elev,
                AVG(speed) as avg_speed,
                AVG(gap) as avg_gap,
                AVG(perf) as avg_perf,
                AVG(rw_idx) as avg_rw_idx
            FROM segments
            GROUP BY 1, 2, 3, segment_id
            HAVING duration_sec >= 10
            ORDER BY activity_id, start_time ASC
            """
            rows = list(client.query(query_tel_series).result())

            series_data: dict[str, list[str]] = {}
            for row in rows:
                key = f"{row.activity_name} (ID: {row.activity_id})"
                if key not in series_data:
                    series_data[key] = []

                label = "WORK" if row.is_work else "REST"
                dur = f"{int(row.duration_sec)}s"

                def mps_to_pace(mps: float) -> str:
                    if not mps or mps < 0.5:
                        return "N/A"
                    total_seconds = 1000 / mps
                    return f"{int(total_seconds // 60)}:{int(total_seconds % 60):02d}"

                metrics = [
                    f"DUR:{dur}",
                    f"HR:{int(row.avg_hr or 0)} (max {int(row.max_hr or 0)})",
                    f"PWR:{int(row.avg_pwr or 0)}W (max {int(row.max_pwr or 0)}W)",
                    f"PACE:{mps_to_pace(row.avg_speed or 0)} (GAP:{mps_to_pace(row.avg_gap or 0)})",
                    f"CAD:{round(row.avg_cad or 0, 1)}spm",
                    f"STRIDE:{round((row.avg_stride or 0) / 1000, 2)}m",
                    f"GCT:{int(row.avg_gct or 0)}ms",
                    f"VOSC:{round(row.avg_osc or 0, 1)}cm",
                    f"VRATIO:{round(row.avg_v_ratio or 0, 1)}%",
                    f"VSPD:{round(row.avg_v_speed or 0, 2)}m/s",
                    f"ELEV:{round(row.avg_elev or 0, 1)}m",
                    f"BBAT:{int(row.avg_battery or 0)}",
                    f"TEMP:{int(row.avg_temp or 0)}C",
                    f"PERF:{int(row.avg_perf or 0)}",
                    f"RW:{int(row.avg_rw_idx or 0)}",
                ]

                series_data[key].append(f"{label}[{'|'.join(metrics)}]")

            compact_series = []
            for activity_label, segments_list in series_data.items():
                compact_series.append(f"{activity_label}: {' '.join(segments_list)}")

            log.info(
                f"⏱️ BigQuery: Telemetry event segments retrieved in {time.time() - t0:.2f}s ({len(rows)} segments)"
            )
            return "last_3_runs_timeseries_summary", (
                "\n".join(compact_series) if compact_series else "No detailed telemetry found."
            )
        except Exception as e:
            log.error(f"❌ Telemetry retrieval failed: {e}")
            return (
                "last_3_runs_timeseries_summary",
                f"Error retrieving telemetry: {e}",
            )

    # Execute first queries in parallel
    with ThreadPoolExecutor(max_workers=7) as executor:
        f_act = executor.submit(fetch_activities)
        f_status = executor.submit(fetch_training_status)
        f_sleep = executor.submit(fetch_sleep_history)
        f_hrv = executor.submit(fetch_hrv_history)
        f_profile = executor.submit(fetch_user_profile)
        f_body = executor.submit(fetch_body_composition)
        f_health = executor.submit(fetch_health_status)
        f_goals = executor.submit(fetch_user_goals)
        f_daily = executor.submit(fetch_daily_physiology)
        f_calib = executor.submit(fetch_calibration_profile)
        f_sched = executor.submit(fetch_scheduled_workouts)

        act_key, act_val = f_act.result()
        context[act_key] = act_val

        f_telemetry = executor.submit(fetch_telemetry, top_3_ids)

        for f in [
            f_status,
            f_sleep,
            f_hrv,
            f_profile,
            f_body,
            f_health,
            f_goals,
            f_daily,
            f_calib,
            f_sched,
            f_telemetry,
        ]:
            res: tuple[str, Any] = f.result()  # type: ignore
            key, val = res
            context[key] = val

    # Fill in info for missing fields
    if not context.get("recent_activities"):
        context["recent_activities"] = [{"info": "No activity history found in Data Lake."}]
    if not context.get("training_status"):
        context["training_status"] = {"info": "No training status available."}
    if not context.get("sleep"):
        context["sleep"] = {"info": "Sleep data not found (normal if watch not worn during sleep)."}
    if not context.get("hrv"):
        context["hrv"] = [{"info": "HRV baseline not yet established."}]

    log.info(f"✅ Total context retrieval time: {time.time() - start_total:.2f}s")

    def serialize_dates(obj: Any) -> Any:
        """Serializes dates and datetimes to ISO format."""
        if isinstance(obj, dict):
            return {k: serialize_dates(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize_dates(i) for i in obj]
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return obj

    return serialize_dates(context)


def _get_mock_data() -> dict[str, Any]:
    """Returns mock data when GCP environment is not available."""
    return {
        "recent_activities": [
            {
                "date": "2024-10-01",
                "type": "running",
                "distance_km": 10.5,
                "avg_hr": 145,
                "zone": "Z3",
            },
            {
                "date": "2024-10-03",
                "type": "running",
                "distance_km": 5.0,
                "avg_hr": 125,
                "zone": "Z2",
            },
        ],
        "readiness": {
            "sleep_score": 58,
            "hrv_status": "unbalanced",
            "recovery_time_hours": 36,
        },
    }
