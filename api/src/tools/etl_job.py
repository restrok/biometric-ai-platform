import logging
import os
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
from garmin_training_toolkit_sdk.utils import find_token_file, get_authenticated_client

from src.utils.config import setup_environment

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
    """Uploads data to a NATIVE BigQuery table (supports appending)."""
    if df.empty:
        return

    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_NAME}.{table_name}"

    # Configure the load job
    job_config = bigquery.LoadJobConfig(
        write_disposition=mode,
        source_format=bigquery.SourceFormat.PARQUET,
    )

    local_path = Path(f"/tmp/{table_name}.parquet")
    df.to_parquet(local_path, engine="pyarrow", index=False)

    # Upload to GCS (Archive / Audit Log)
    gcs_client = storage.Client(project=PROJECT_ID)
    bucket = gcs_client.bucket(BUCKET_NAME)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    blob_path = f"archive/{folder_name}/{table_name}_{timestamp}.parquet"
    bucket.blob(blob_path).upload_from_filename(str(local_path))

    # Load into BigQuery (Native Table)
    with open(local_path, "rb") as source_file:
        job = client.load_table_from_file(source_file, table_id, job_config=job_config)

    job.result()  # Wait for completion
    log.info(f"Synced {len(df)} rows to {table_id} ({mode}).")


def run_etl():
    log.info("Starting Incremental Biometric Sync...")

    token_file = find_token_file()
    if not token_file:
        log.error("Garmin authentication token not found.")
        return

    client = get_authenticated_client(token_file)
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
            df_act = pd.DataFrame([a.model_dump() for a in new_activities])
            if "splits" in df_act.columns:
                df_act.drop(columns=["splits"], inplace=True)
            df_act["date"] = pd.to_datetime(df_act["date"])
            upload_to_bq(df_act, "recent_activities", "activities", mode="WRITE_APPEND")

            # --- 2. Telemetry for the NEW activities ONLY ---
            all_telemetry = []
            for act in new_activities:
                log.info(f"Fetching telemetry for new activity: {act.name} ({act.id})")
                telemetry = get_activity_telemetry(client, act.id)
                if telemetry and telemetry.ticks:
                    df_t = pd.DataFrame([t.model_dump() for t in telemetry.ticks])
                    df_t["activity_id"] = str(act.id)
                    df_t["activity_name"] = act.name
                    all_telemetry.append(df_t)

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
        upload_to_bq(pd.DataFrame([status.model_dump()]), "training_status", "biometrics", mode="WRITE_TRUNCATE")

    # --- 5. User Profile (Always refresh latest) ---
    try:
        log.info("Syncing User Profile...")
        profile = get_user_profile(client)
        if profile:
            df_profile = pd.DataFrame([profile.model_dump()])
            df_profile["updated_at"] = datetime.utcnow()
            upload_to_bq(df_profile, "user_profile", "biometrics", mode="WRITE_TRUNCATE")
    except Exception as e:
        log.warning(f"User Profile sync failed: {e}")

    # --- 6. Body Composition (Incremental) ---
    try:
        last_body_date = get_last_sync_date("body_composition")
        start_body = (last_body_date + timedelta(days=1)) if last_body_date else (datetime.now() - timedelta(days=30))

        if start_body.date() <= end_date.date():
            log.info(f"Syncing Body Composition from {start_body.date()}...")
            body_data = get_body_composition(client, start_body.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
            if body_data:
                df_body = pd.DataFrame([b.model_dump() for b in body_data])
                upload_to_bq(df_body, "body_composition", "biometrics", mode="WRITE_APPEND")
    except Exception as e:
        log.warning(f"Body Composition sync failed: {e}")

    log.info("Incremental Sync Complete!")


if __name__ == "__main__":
    run_etl()
