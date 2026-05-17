"""Incremental Biometric Sync (ETL) from Garmin to BigQuery."""

import logging
import os
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import google.cloud.bigquery as bigquery
import google.cloud.storage as storage
import pandas as pd
from garmin_training_toolkit_sdk.extractors import get_training_status
from garmin_training_toolkit_sdk.extractors.biometrics import get_body_composition

from src.utils.config import setup_environment

# Initialize environment
setup_environment()

# Configure logging
log = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
BUCKET_NAME = os.getenv("DATALAKE_BUCKET")
DATASET_NAME = os.getenv("DATASET_NAME", "biometric_data_dev")

if not PROJECT_ID or not BUCKET_NAME:
    raise ValueError("GOOGLE_CLOUD_PROJECT and DATALAKE_BUCKET environment variables must be set.")


def get_last_sync_date(table_name: str, user_id: str | None = None) -> pd.Timestamp | None:
    """Queries BigQuery to find the latest date stored in a table.

    Args:
        table_name: Name of the BigQuery table.
        user_id: Optional user ID to filter by.

    Returns:
        The latest date as a pandas Timestamp, or None if not found.
    """
    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_NAME}.{table_name}"
    try:
        where_clause = f"WHERE user_id = '{user_id}'" if user_id else ""
        query = f"SELECT MAX(date) as last_date FROM `{table_id}` {where_clause}"
        results = client.query(query).result()
        row = next(results)
        if row.last_date:
            return pd.to_datetime(row.last_date)
    except Exception:
        log.info(f"Table {table_name} not found or empty (user: {user_id}). Starting from scratch.")
    return None


def upsert_to_bq(
    df: pd.DataFrame,
    table_name: str,
    unique_key: str = "date",
    user_id: str | None = None,
) -> None:
    """Performs an atomic UPSERT in BigQuery.

    Automatically aligns DataFrame types with target table schema.

    Args:
        df: DataFrame containing the data to upload.
        table_name: Target BigQuery table name.
        unique_key: Column name used as the unique identifier for merging.
        user_id: Optional user ID to add to each row.
    """
    if df.empty:
        return

    # Add user_id to the dataframe before uploading
    if user_id:
        df["user_id"] = user_id

    client = bigquery.Client(project=PROJECT_ID)
    target_table_id = f"{PROJECT_ID}.{DATASET_NAME}.{table_name}"

    # 0. Align types with target table to avoid schema mismatches
    try:
        target_table = client.get_table(target_table_id)
        target_schema = {f.name: f.field_type for f in target_table.schema}

        for col in df.columns:
            if col in target_schema:
                bqt = target_schema[col]
                if bqt == "INTEGER":
                    if col == "date" or col.endswith("_at"):
                        # Ensure we convert datetime to SECONDS, not nanoseconds
                        df[col] = pd.to_datetime(df[col], errors="coerce").view("int64") // 10**9
                        # Replace negative/very small values with 0
                        df.loc[df[col] < 0, col] = 0
                    else:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
                elif bqt == "FLOAT":
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
                elif bqt == "STRING":
                    df[col] = df[col].astype(str).replace("None", None).replace("nan", None)
                elif bqt in ["DATETIME", "TIMESTAMP"]:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                elif bqt == "BOOLEAN":
                    df[col] = df[col].astype(bool)
    except Exception as e:
        log.warning(f"Could not align types for {table_name} (might be a new table): {e}")

    staging_table_name = f"{table_name}_staging_{int(datetime.now().timestamp())}"
    staging_table_id = f"{PROJECT_ID}.{DATASET_NAME}.{staging_table_name}"

    # 1. Load data to staging table
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    client.load_table_from_dataframe(df, staging_table_id, job_config=job_config).result()

    # 2. Sync Schema (Add missing columns to target table)
    staging_table = client.get_table(staging_table_id)
    try:
        target_table = client.get_table(target_table_id)
        target_fields = {f.name for f in target_table.schema}
        missing_fields = [f for f in staging_table.schema if f.name not in target_fields]

        if missing_fields:
            log.info(
                f"Updating schema for {table_name}: adding fields {[f.name for f in missing_fields]} (user: {user_id})."
            )
            new_schema = list(target_table.schema) + missing_fields
            target_table.schema = new_schema
            client.update_table(target_table, ["schema"])
    except Exception as e:
        log.warning(f"Schema sync for {table_name} failed: {e}. Attempting MERGE anyway.")

    # 3. Perform MERGE
    cols = [field.name for field in staging_table.schema]
    update_set = ", ".join([f"T.`{c}` = S.`{c}`" for c in cols if c not in [unique_key, "user_id"]])
    insert_cols = ", ".join([f"`{c}`" for c in cols])
    insert_values = ", ".join([f"S.`{c}`" for c in cols])

    on_clause = f"T.`{unique_key}` = S.`{unique_key}`"
    if user_id:
        on_clause += " AND T.`user_id` = S.`user_id`"

    merge_query = f"""
        MERGE `{target_table_id}` T
        USING `{staging_table_id}` S
        ON {on_clause}
        WHEN MATCHED THEN
            UPDATE SET {update_set}
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols}) VALUES ({insert_values})
    """

    try:
        client.query(merge_query).result()
        log.info(f"Successfully merged {len(df)} rows into {table_name} using key '{unique_key}' (user: {user_id}).")
    finally:
        client.delete_table(staging_table_id, not_found_ok=True)


def upload_to_bq(
    df: pd.DataFrame,
    table_name: str,
    folder_name: str,
    mode: str = "WRITE_APPEND",
    user_id: str | None = None,
) -> None:
    """Uploads data to a native BigQuery table.

    Also archives a copy to GCS as Parquet.

    Args:
        df: DataFrame containing the data to upload.
        table_name: Target BigQuery table name.
        folder_name: Folder name for GCS archival.
        mode: BigQuery write disposition (e.g., 'WRITE_APPEND').
        user_id: Optional user ID to add to each row.
    """
    if df.empty:
        return

    # Add user_id to the dataframe before uploading
    if user_id:
        df["user_id"] = user_id

    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_NAME}.{table_name}"

    job_config = bigquery.LoadJobConfig(write_disposition=mode)

    if mode == "WRITE_APPEND":
        job_config.schema_update_options = [
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
            bigquery.SchemaUpdateOption.ALLOW_FIELD_RELAXATION,
        ]

    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()

    # Archive to GCS as Parquet for audit
    try:
        local_path = Path(f"/tmp/{table_name}.parquet")
        df.to_parquet(local_path, engine="pyarrow", index=False)
        gcs_client = storage.Client(project=PROJECT_ID)
        bucket = gcs_client.bucket(BUCKET_NAME)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{user_id}" if user_id else ""
        blob_path = f"archive/{folder_name}/{table_name}{suffix}_{timestamp}.parquet"
        bucket.blob(blob_path).upload_from_filename(str(local_path))
    except Exception as e:
        log.warning(f"GCS archival failed (but BQ load succeeded): {e}")

    log.info(f"Synced {len(df)} rows to {table_id} ({mode}) (user: {user_id}).")


def get_current_user_metrics(user_id: str | None = None) -> tuple[int | None, int | None]:
    """Queries BigQuery to find the current max_hr and resting_hr.

    Args:
        user_id: Optional user ID to filter by.

    Returns:
        A tuple of (max_hr, resting_hr), or (None, None) if not found.
    """
    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_NAME}.user_profile"
    try:
        where_clause = f"WHERE user_id = '{user_id}'" if user_id else ""
        query = f"SELECT max_hr, resting_hr FROM `{table_id}` {where_clause} LIMIT 1"
        results = client.query(query).result()
        row = next(results)
        return row.max_hr, row.resting_hr
    except Exception:
        return None, None


def get_wellness_stats(client: Any, days: int = 7) -> tuple[int | None, int | None]:
    """Retrieves heart rate statistics from wellness data for the last N days.

    Args:
        client: Garmin authentication client.
        days: Number of days to look back.

    Returns:
        A tuple of (average_resting_hr, peak_max_hr).
    """
    if not client.display_name:
        try:
            settings = client.get_userprofile_settings()
            client.display_name = settings.get("displayName")
        except Exception as e:
            log.warning(f"Could not retrieve display_name for wellness sync: {e}")

    resting_hrs = []
    max_hrs = []

    for i in range(1, days + 1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            hr_data = client.get_heart_rates(date)
            if hr_data:
                rhr = hr_data.get("restingHeartRate")
                mhr = hr_data.get("maxHeartRate")
                if rhr:
                    resting_hrs.append(rhr)
                if mhr:
                    max_hrs.append(mhr)
        except Exception as e:
            log.debug(f"Wellness data for {date} not available: {e}")

    avg_rhr = round(statistics.mean(resting_hrs)) if resting_hrs else None
    peak_mhr = max(max_hrs) if max_hrs else None

    return avg_rhr, peak_mhr


def get_manual_weigh_ins(client: Any, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Fetches manual weight entries that might not appear in body composition.

    Args:
        client: Garmin authentication client.
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).

    Returns:
        A list of dictionaries containing manual weigh-in data.
    """
    weigh_ins = []
    try:
        data = client.get_weigh_ins(start_date, end_date)
        if data and "dailyWeightSummaries" in data:
            for summary in data["dailyWeightSummaries"]:
                for m in summary.get("allWeightMetrics", []):
                    weigh_ins.append(
                        {
                            "date": m.get("calendarDate"),
                            "weight_kg": (m.get("weight") / 1000.0 if m.get("weight") else None),
                            "bmi": m.get("bmi"),
                            "fat_percentage": m.get("bodyFat"),
                            "muscle_mass_kg": (m.get("muscleMass") / 1000.0 if m.get("muscleMass") else None),
                        }
                    )
    except Exception as e:
        log.warning(f"Manual weigh-in fetch failed: {e}")
    return weigh_ins


def run_etl(
    user_id: str | None = None,
    days_back: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[str] | None:
    """Runs the incremental ETL process for a given user with safety constraints.

    Args:
        user_id: The ID of the user.
        days_back: Number of days to look back from end_date.
        start_date: Explicit start date (YYYY-MM-DD).
        end_date: Explicit end date (YYYY-MM-DD), defaults to now.

    Returns:
        A list of IDs of newly synced activities, or None.
    """
    log.info(f"Starting Biometric Sync for user: {user_id}...")

    from src.utils.provider_factory import get_provider

    provider = get_provider(user_id=user_id)
    client = getattr(provider, "client", None)

    if not client:
        log.error(f"Garmin authentication client not found in Provider for user {user_id}.")
        return None

    # Calculate effective date range
    final_end = datetime.now()
    if end_date:
        try:
            final_end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            log.error(f"Invalid end_date format: {end_date}. Using now().")

    final_start = None
    if start_date:
        try:
            final_start = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            log.error(f"Invalid start_date format: {start_date}. Falling back to incremental logic.")

    if not final_start:
        if days_back:
            final_start = final_end - timedelta(days=days_back)
        else:
            last_act_date = get_last_sync_date("recent_activities", user_id=user_id)
            if last_act_date and last_act_date.year > 1990:
                final_start = last_act_date - timedelta(days=1)
            else:
                # SAFETY CAP: Default to 3 days if no history found to avoid massive accidental downloads
                final_start = final_end - timedelta(days=3)
                log.warning(
                    f"No valid previous sync date found for user {user_id}. "
                    f"Applying safety cap: syncing only from {final_start.date()}."
                )

    log.info(f"Sync range: {final_start.date()} to {final_end.date()} (user: {user_id}).")

    # --- 1. Incremental Activities ---
    activities = provider.get_activities(final_start.date(), final_end.date())
    newly_synced_ids = []
    
    last_act_date = get_last_sync_date("recent_activities", user_id=user_id)

    if activities:
        new_activities = [
            a
            for a in activities
            if not last_act_date or pd.to_datetime(a.date).tz_localize(None) > last_act_date.tz_localize(None)
        ]

        if new_activities:
            all_telemetry = []
            activity_summaries = []

            for act in new_activities:
                log.info(f"Fetching telemetry for new activity: {act.name} ({act.id})")
                newly_synced_ids.append(str(act.id))
                telemetry = provider.get_telemetry(str(act.id))

                avg_pwr = None
                max_pwr_calc = None
                if telemetry and telemetry.ticks:
                    df_t = pd.DataFrame([t.model_dump() for t in telemetry.ticks])
                    df_t["activity_id"] = str(act.id)
                    df_t["activity_name"] = act.name
                    all_telemetry.append(df_t)

                    if "power_w" in df_t.columns:
                        valid_pwr = df_t[df_t["power_w"] > 0]["power_w"]
                        if not valid_pwr.empty:
                            avg_pwr = float(valid_pwr.mean())
                            max_pwr_calc = float(valid_pwr.max())

                summary = act.model_dump()
                summary["avg_power"] = float(avg_pwr) if avg_pwr is not None else None
                if max_pwr_calc is not None:
                    summary["max_power"] = max_pwr_calc
                activity_summaries.append(summary)

            df_act = pd.DataFrame(activity_summaries)
            if "splits" in df_act.columns:
                df_act.drop(columns=["splits"], inplace=True)

            upsert_to_bq(df_act, "recent_activities", unique_key="id", user_id=user_id)

            if all_telemetry:
                df_telemetry = pd.concat(all_telemetry)
                if "run_walk_index" in df_telemetry.columns:
                    df_telemetry["run_walk_index"] = df_telemetry["run_walk_index"].astype(float)
                upload_to_bq(
                    df_telemetry,
                    "latest_activity_telemetry",
                    "telemetry",
                    mode="WRITE_APPEND",
                    user_id=user_id,
                )
        else:
            log.info(f"No new activities to sync for user {user_id}.")

    # --- 3. Incremental Sleep ---
    last_sleep_date = get_last_sync_date("sleep_history", user_id=user_id)
    start_sleep = (last_sleep_date - timedelta(days=3)) if last_sleep_date else (final_end - timedelta(days=7))

    if start_sleep.date() <= final_end.date():
        log.info(f"Syncing Sleep from {start_sleep.date()} to {final_end.date()} (user: {user_id})...")
        sleep_data = provider.get_sleep_history(start_sleep.date(), final_end.date())
        log.info(f"Retrieved {len(sleep_data)} sleep records from Provider.")
        if sleep_data:
            df_sleep = pd.DataFrame([s.model_dump() for s in sleep_data])
            try:
                int_cols = [
                    "start",
                    "end",
                    "duration_sec",
                    "deep_sec",
                    "light_sec",
                    "rem_sec",
                    "awake_sec",
                    "quality",
                ]
                for col in int_cols:
                    if col in df_sleep.columns:
                        df_sleep[col] = df_sleep[col].astype("Int64")

                upsert_to_bq(df_sleep, "sleep_history", unique_key="date", user_id=user_id)
            except Exception as e:
                log.error(f"Sleep sync failed during upload: {e}")

    # --- 3b. Incremental HRV ---
    last_hrv_date = get_last_sync_date("hrv_history", user_id=user_id)
    start_hrv = (last_hrv_date - timedelta(days=3)) if last_hrv_date else (final_end - timedelta(days=7))

    if start_hrv.date() <= final_end.date():
        log.info(f"Syncing HRV from {start_hrv.date()} to {final_end.date()} (user: {user_id})...")
        hrv_data = provider.get_hrv_history(start_hrv.date(), final_end.date())
        log.info(f"Retrieved {len(hrv_data)} HRV records from Provider.")
        if hrv_data:
            df_hrv = pd.DataFrame([h.model_dump() for h in hrv_data])
            # The SDK was updated to use 'last_night_avg', but our BigQuery schema expects 'avg_hrv'
            if "last_night_avg" in df_hrv.columns:
                df_hrv.rename(columns={"last_night_avg": "avg_hrv"}, inplace=True)
            try:
                upsert_to_bq(df_hrv, "hrv_history", unique_key="date", user_id=user_id)
            except Exception as e:
                log.error(f"HRV sync failed during upload: {e}")

    # --- 4. Training Status ---
    status = get_training_status(client, final_end.strftime("%Y-%m-%d"))
    if status:
        if status.vo2max is None:
            try:
                query = (
                    f"SELECT vo2max FROM `{PROJECT_ID}.{DATASET_NAME}.recent_activities` "
                    f"WHERE vo2max IS NOT NULL AND user_id = '{user_id}' "
                    f"ORDER BY date DESC LIMIT 1"
                )
                bq_client = bigquery.Client(project=PROJECT_ID)
                results = bq_client.query(query).result()
                row = next(results)
                if row.vo2max:
                    status.vo2max = row.vo2max
                    log.info(f"Patched VO2 Max from latest activity: {row.vo2max}")
            except Exception:
                pass

        upsert_to_bq(
            pd.DataFrame([status.model_dump()]),
            "training_status",
            unique_key="user_id",
            user_id=user_id,
        )

    # --- 5. User Profile ---
    try:
        log.info(f"Syncing User Profile & Wellness Metrics for user {user_id}...")
        profile = provider.get_user_profile()
        if profile:
            curr_max, curr_rest = get_current_user_metrics(user_id=user_id)
            avg_rhr, peak_mhr = get_wellness_stats(client)

            df_profile = pd.DataFrame([profile.model_dump()])

            if pd.isna(df_profile["max_hr"].iloc[0]):
                potential_maxes = [m for m in [peak_mhr, curr_max] if m]
                fallback_max = max(potential_maxes) if potential_maxes else None
                if fallback_max:
                    df_profile.loc[0, "max_hr"] = fallback_max
                    log.info(f"Patched Max HR with highest fallback: {fallback_max}")

            if pd.isna(df_profile["resting_hr"].iloc[0]):
                fallback_rest = avg_rhr or curr_rest
                if fallback_rest:
                    df_profile.loc[0, "resting_hr"] = fallback_rest
                    log.info(f"Patched Resting HR with fallback: {fallback_rest}")

            df_profile["updated_at"] = datetime.utcnow()
            upsert_to_bq(df_profile, "user_profile", unique_key="user_id", user_id=user_id)
    except Exception as e:
        log.warning(f"User Profile sync failed: {e}")

    # --- 6. Body Composition ---
    try:
        last_body_date = get_last_sync_date("body_composition", user_id=user_id)
        start_body = (last_body_date + timedelta(days=1)) if last_body_date else (final_end - timedelta(days=7))

        if start_body.date() <= final_end.date():
            start_str = start_body.strftime("%Y-%m-%d")
            end_str = final_end.strftime("%Y-%m-%d")

            log.info(f"Syncing Body Composition from {start_str} to {end_str} (user: {user_id})...")
            body_data = get_body_composition(client, start_str, end_str)
            df_body = pd.DataFrame([b.model_dump() for b in body_data]) if body_data else pd.DataFrame()

            manual_data = get_manual_weigh_ins(client, start_str, end_str)
            if manual_data:
                df_manual = pd.DataFrame(manual_data)
                df_body = pd.concat([df_body, df_manual]).drop_duplicates(subset=["date"], keep="first")

            if not df_body.empty:
                df_body["date"] = pd.to_datetime(df_body["date"]).dt.date
                df_body = df_body.dropna(subset=["date"])

                profile = provider.get_user_profile()
                if profile and profile.height_cm:
                    height_m = profile.height_cm / 100.0
                    df_body["bmi"] = df_body.apply(
                        lambda row: round(row["weight_kg"] / (height_m**2), 1) if pd.isna(row["bmi"]) else row["bmi"],
                        axis=1,
                    )

                for col in ["weight_kg", "bmi", "fat_percentage", "muscle_mass_kg"]:
                    if col in df_body.columns:
                        df_body[col] = df_body[col].astype(float)
                upsert_to_bq(df_body, "body_composition", unique_key="date", user_id=user_id)
    except Exception as e:
        log.warning(f"Body Composition sync failed: {e}")

    # --- 7. Scheduled Workouts ---
    try:
        log.info(f"Syncing Scheduled Workouts for user {user_id}...")
        now = datetime.now()
        end_window = now + timedelta(days=14)

        all_calendar_items = provider.get_calendar_range(now.date(), end_window.date())

        bq_client = bigquery.Client(project=PROJECT_ID)
        delete_query = f"""
            DELETE FROM `{PROJECT_ID}.{DATASET_NAME}.scheduled_workouts`
            WHERE user_id = '{user_id}'
        """
        log.info(f"Performing total calendar wipe for {user_id} in BigQuery...")
        bq_client.query(delete_query).result()

        if all_calendar_items:
            df_cal = pd.DataFrame(all_calendar_items)
            df_cal["date"] = pd.to_datetime(df_cal["date"])
            df_cal = df_cal[df_cal["date"].dt.date >= now.date()]

            if "itemType" in df_cal.columns:
                df_cal = df_cal[df_cal["itemType"] == "workout"]

            if not df_cal.empty:
                if "calendarItemId" in df_cal.columns:
                    df_cal["id"] = df_cal["calendarItemId"].fillna(df_cal.get("id", pd.NA))
                elif "id" in df_cal.columns:
                    df_cal["id"] = df_cal["id"]
                else:
                    return None

                df_cal = df_cal.drop_duplicates(subset=["id"])

                final_cal = pd.DataFrame()
                final_cal["id"] = df_cal["id"]
                final_cal["workout_id"] = df_cal.get("workoutId", pd.NA)
                final_cal["title"] = df_cal.get("title", "Untitled Workout")
                final_cal["date"] = df_cal["date"].dt.date
                final_cal["sport_type"] = df_cal.get("sportTypeKey", "running")
                final_cal["description"] = ""
                final_cal["duration_sec"] = df_cal.get("duration", 0)
                final_cal["distance_m"] = df_cal.get("distance", 0)
                final_cal["updated_at"] = datetime.utcnow()

                upload_to_bq(
                    final_cal,
                    "scheduled_workouts",
                    "biometrics",
                    mode="WRITE_APPEND",
                    user_id=user_id,
                )
            else:
                log.info(f"No workouts found in Garmin calendar range for {user_id}.")
        else:
            log.info(f"Garmin calendar is empty for {user_id}. BigQuery remains clean.")
    except Exception as e:
        log.warning(f"Scheduled Workouts sync failed: {e}")

    log.info(f"Incremental Sync Complete for user {user_id}!")
    return newly_synced_ids


if __name__ == "__main__":
    run_etl()
