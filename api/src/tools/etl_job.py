import logging
import os
import statistics
from datetime import datetime, timedelta
from pathlib import Path

import google.cloud.bigquery as bigquery
import google.cloud.storage as storage
import pandas as pd

# Import our custom SDK
from garmin_training_toolkit_sdk.extractors import (
    get_activities,
    get_activity_telemetry,
    get_sleep_data,
    get_training_status,
)
from garmin_training_toolkit_sdk.extractors.biometrics import get_body_composition, get_user_profile
from garmin_training_toolkit_sdk.utils import find_token_file

from src.utils.config import setup_environment
from src.utils.garmin_auth import get_robust_client

# Initialize environment
setup_environment()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# Config
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
BUCKET_NAME = os.getenv("DATALAKE_BUCKET")
DATASET_NAME = os.getenv("DATASET_NAME", "biometric_data_dev")

if not PROJECT_ID or not BUCKET_NAME:
    raise ValueError("GOOGLE_CLOUD_PROJECT and DATALAKE_BUCKET environment variables must be set.")


def get_last_sync_date(table_name):
    """Queries BigQuery to find the latest date we have stored."""
    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_NAME}.{table_name}"
    try:
        query = f"SELECT MAX(date) as last_date FROM `{table_id}`"
        results = client.query(query).result()
        row = next(results)
        if row.last_date:
            return pd.to_datetime(row.last_date)
    except Exception:
        log.info(f"Table {table_name} not found or empty. Starting from scratch.")
    return None


def upload_to_bq(df, table_name, folder_name, mode="WRITE_APPEND"):
    """Uploads data to a NATIVE BigQuery table."""
    if df.empty:
        return

    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_NAME}.{table_name}"

    # Configure the load job
    job_config = bigquery.LoadJobConfig(
        write_disposition=mode,
    )

    # Load into BigQuery
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # Wait for completion

    # Optional: Still archive to GCS as Parquet for audit
    try:
        local_path = Path(f"/tmp/{table_name}.parquet")
        df.to_parquet(local_path, engine="pyarrow", index=False)
        gcs_client = storage.Client(project=PROJECT_ID)
        bucket = gcs_client.bucket(BUCKET_NAME)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        blob_path = f"archive/{folder_name}/{table_name}_{timestamp}.parquet"
        bucket.blob(blob_path).upload_from_filename(str(local_path))
    except Exception as e:
        log.warning(f"GCS archival failed (but BQ load succeeded): {e}")

    log.info(f"Synced {len(df)} rows to {table_id} ({mode}).")


def get_current_user_metrics():
    """Queries BigQuery to find the current max_hr and resting_hr."""
    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_NAME}.user_profile"
    try:
        query = f"SELECT max_hr, resting_hr FROM `{table_id}` LIMIT 1"
        results = client.query(query).result()
        row = next(results)
        return row.max_hr, row.resting_hr
    except Exception:
        return None, None


def get_wellness_stats(client, days=7):
    """Retrieves heart rate statistics from wellness data for the last N days."""
    # Ensure display_name is set for wellness API calls
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


def get_manual_weigh_ins(client, start_date, end_date):
    """Fetches manual weight entries that might not appear in body composition."""
    weigh_ins = []
    try:
        data = client.get_weigh_ins(start_date, end_date)
        if data and "dailyWeightSummaries" in data:
            for summary in data["dailyWeightSummaries"]:
                for m in summary.get("allWeightMetrics", []):
                    # Weight is in grams in this endpoint
                    weigh_ins.append(
                        {
                            "date": m.get("calendarDate"),
                            "weight_kg": m.get("weight") / 1000.0 if m.get("weight") else None,
                            "bmi": m.get("bmi"),
                            "fat_percentage": m.get("bodyFat"),
                            "muscle_mass_kg": m.get("muscleMass") / 1000.0 if m.get("muscleMass") else None,
                        }
                    )
    except Exception as e:
        log.warning(f"Manual weigh-in fetch failed: {e}")
    return weigh_ins


def run_etl():
    log.info("Starting Incremental Biometric Sync...")

    token_file = find_token_file()
    if not token_file:
        log.error("Garmin authentication token not found.")
        return

    client = get_robust_client(token_file)
    end_date = datetime.now()

    # --- 1. Incremental Activities ---
    last_act_date = get_last_sync_date("recent_activities")
    # Buffer: overlaps by 1 day to be safe, then we filter duplicates
    start_date = (last_act_date - timedelta(days=1)) if last_act_date else (datetime.now() - timedelta(days=30))

    log.info(f"Checking for Activities since {start_date.date()}...")
    activities = get_activities(client, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

    if activities:
        # Deduplication logic: only keep activities we don't have
        new_activities = [
            a
            for a in activities
            if not last_act_date or pd.to_datetime(a.date).tz_localize(None) > last_act_date.tz_localize(None)
        ]

        if new_activities:
            # --- 2. Telemetry for the NEW activities ONLY ---
            all_telemetry = []
            activity_summaries = []

            for act in new_activities:
                log.info(f"Fetching telemetry for new activity: {act.name} ({act.id})")
                telemetry = get_activity_telemetry(client, act.id)

                avg_pwr = None
                if telemetry and telemetry.ticks:
                    df_t = pd.DataFrame([t.model_dump() for t in telemetry.ticks])
                    df_t["activity_id"] = str(act.id)
                    df_t["activity_name"] = act.name
                    all_telemetry.append(df_t)

                    # Delegate math to pandas/local processing for the new rows before upload
                    if "power_w" in df_t.columns:
                        valid_pwr = df_t[df_t["power_w"] > 0]["power_w"]
                        if not valid_pwr.empty:
                            avg_pwr = float(valid_pwr.mean())

                # Build summary row
                summary = act.model_dump()
                summary["avg_power"] = avg_pwr
                activity_summaries.append(summary)

            # Upload Activity Summaries
            df_act = pd.DataFrame(activity_summaries)
            if "splits" in df_act.columns:
                df_act.drop(columns=["splits"], inplace=True)
            df_act["date"] = pd.to_datetime(df_act["date"])
            upload_to_bq(df_act, "recent_activities", "activities", mode="WRITE_APPEND")

            # Upload Telemetry
            if all_telemetry:
                df_telemetry = pd.concat(all_telemetry)
                # Fix schema mismatch: ensure run_walk_index is float to match BQ
                if "run_walk_index" in df_telemetry.columns:
                    df_telemetry["run_walk_index"] = df_telemetry["run_walk_index"].astype(float)
                upload_to_bq(df_telemetry, "latest_activity_telemetry", "telemetry", mode="WRITE_APPEND")
        else:
            log.info("No new activities to sync.")

    # --- 3. Incremental Sleep ---
    last_sleep_date = get_last_sync_date("sleep_history")
    start_sleep = (last_sleep_date + timedelta(days=1)) if last_sleep_date else (datetime.now() - timedelta(days=30))

    if start_sleep.date() <= end_date.date():
        log.info(f"Syncing Sleep from {start_sleep.date()} to {end_date.date()}...")
        sleep_data = get_sleep_data(client, start_sleep.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        log.info(f"Retrieved {len(sleep_data)} sleep records from SDK.")
        if sleep_data:
            df_sleep = pd.DataFrame([s.model_dump() for s in sleep_data])
            try:
                upload_to_bq(df_sleep, "sleep_history", "biometrics", mode="WRITE_APPEND")
            except Exception as e:
                log.error(f"Sleep sync failed during upload: {e}")
        else:
            log.info("No sleep data returned from SDK for this range.")

    # --- 4. Training Status (Always refresh latest) ---
    status = get_training_status(client, end_date.strftime("%Y-%m-%d"))
    if status:
        # Fallback for VO2 Max: if not in training status, check latest activity
        if status.vo2max is None:
            try:
                query = f"SELECT vo2max FROM `{PROJECT_ID}.{DATASET_NAME}.recent_activities` WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
                bq_client = bigquery.Client(project=PROJECT_ID)
                results = bq_client.query(query).result()
                row = next(results)
                if row.vo2max:
                    status.vo2max = row.vo2max
                    log.info(f"Patched VO2 Max from latest activity: {row.vo2max}")
            except Exception:
                pass

        upload_to_bq(pd.DataFrame([status.model_dump()]), "training_status", "biometrics", mode="WRITE_TRUNCATE")

    # --- 5. User Profile (Always refresh latest, but preserve/patch custom HRs) ---
    try:
        log.info("Syncing User Profile & Wellness Metrics...")
        profile = get_user_profile(client)
        if profile:
            curr_max, curr_rest = get_current_user_metrics()
            # Fetch wellness fallbacks (7-day stats)
            avg_rhr, peak_mhr = get_wellness_stats(client)

            df_profile = pd.DataFrame([profile.model_dump()])

            # Patch Max HR
            if pd.isna(df_profile["max_hr"].iloc[0]):
                # Take the highest between the 7-day peak and what we have in BQ
                potential_maxes = [m for m in [peak_mhr, curr_max] if m]
                fallback_max = max(potential_maxes) if potential_maxes else None
                if fallback_max:
                    df_profile.loc[0, "max_hr"] = fallback_max
                    log.info(f"Patched Max HR with highest fallback: {fallback_max}")

            # Patch Resting HR
            if pd.isna(df_profile["resting_hr"].iloc[0]):
                # 1. Try wellness average from last 7 days
                # 2. Try what we already have in BQ
                fallback_rest = avg_rhr or curr_rest
                if fallback_rest:
                    df_profile.loc[0, "resting_hr"] = fallback_rest
                    log.info(f"Patched Resting HR with fallback: {fallback_rest}")

            df_profile["updated_at"] = datetime.utcnow()
            upload_to_bq(df_profile, "user_profile", "biometrics", mode="WRITE_TRUNCATE")
    except Exception as e:
        log.warning(f"User Profile sync failed: {e}")

    # --- 6. Body Composition (Incremental) ---
    try:
        last_body_date = get_last_sync_date("body_composition")
        start_body = (last_body_date + timedelta(days=1)) if last_body_date else (datetime.now() - timedelta(days=30))

        if start_body.date() <= end_date.date():
            start_str = start_body.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")

            log.info(f"Syncing Body Composition from {start_str}...")
            # 1. Try smart scale data
            body_data = get_body_composition(client, start_str, end_str)
            df_body = pd.DataFrame([b.model_dump() for b in body_data]) if body_data else pd.DataFrame()

            # 2. Try manual weigh-ins
            manual_data = get_manual_weigh_ins(client, start_str, end_str)
            if manual_data:
                df_manual = pd.DataFrame(manual_data)
                df_body = pd.concat([df_body, df_manual]).drop_duplicates(subset=["date"], keep="first")

            if not df_body.empty:
                df_body["date"] = pd.to_datetime(df_body["date"])
                df_body = df_body.dropna(subset=["date"])

                # Auto-calculate BMI if missing
                profile = get_user_profile(client)
                if profile and profile.height_cm:
                    height_m = profile.height_cm / 100.0
                    df_body["bmi"] = df_body.apply(
                        lambda row: round(row["weight_kg"] / (height_m**2), 1) if pd.isna(row["bmi"]) else row["bmi"],
                        axis=1,
                    )
                    log.info("Calculated missing BMI values using profile height.")

                # Ensure metrics are float to match BQ schema
                for col in ["weight_kg", "bmi", "fat_percentage", "muscle_mass_kg"]:
                    if col in df_body.columns:
                        df_body[col] = df_body[col].astype(float)
                upload_to_bq(df_body, "body_composition", "biometrics", mode="WRITE_APPEND")
    except Exception as e:
        log.warning(f"Body Composition sync failed: {e}")

    log.info("Incremental Sync Complete!")


if __name__ == "__main__":
    run_etl()
