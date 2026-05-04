import os
import logging
from datetime import date
import pandas as pd
from src.utils.provider_factory import get_provider
from src.tools.etl_job import upsert_to_bq, upload_to_bq
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def manual_import(start_date, end_date):
    provider = get_provider()
    
    log.info(f"Fetching activities from {start_date} to {end_date}...")
    activities = provider.get_activities(start_date, end_date)
    
    if not activities:
        log.info("No activities found for this range.")
        return

    activity_summaries = []
    for act in activities:
        log.info(f"Processing activity: {act.name} ({act.id}) - {act.date}")
        
        # 1. Fetch Telemetry
        telemetry = provider.get_telemetry(str(act.id))
        if telemetry and telemetry.ticks:
            df_t = pd.DataFrame([t.model_dump() for t in telemetry.ticks])
            df_t["activity_id"] = str(act.id)
            df_t["activity_name"] = act.name
            
            # Ensure types for BQ
            if "run_walk_index" in df_t.columns:
                df_t["run_walk_index"] = df_t["run_walk_index"].astype(float)
            
            log.info(f"Uploading {len(df_t)} telemetry ticks...")
            # Use a simple upload for telemetry (or upsert if you prefer, but ID is string)
            # To be safe and avoid duplicates if re-run:
            client = bigquery.Client()
            proj = os.getenv("GOOGLE_CLOUD_PROJECT")
            ds = os.getenv("DATASET_NAME", "biometric_data_dev")
            client.query(f"DELETE FROM `{proj}.{ds}.latest_activity_telemetry` WHERE activity_id = '{act.id}'").result()
            upload_to_bq(df_t, "latest_activity_telemetry", "telemetry")

            # Calculate avg power if available
            avg_pwr = None
            if "power_w" in df_t.columns:
                valid_pwr = df_t[df_t["power_w"] > 0]["power_w"]
                if not valid_pwr.empty:
                    avg_pwr = float(valid_pwr.mean())
            
            summary = act.model_dump()
            summary["avg_power"] = avg_pwr
            activity_summaries.append(summary)

    if activity_summaries:
        df_act = pd.DataFrame(activity_summaries)
        
        # 1. Convert date to nanoseconds (int64) to match BQ schema
        df_act["date"] = pd.to_datetime(df_act["date"]).astype(int)
        
        # 2. Filter for only the columns supported by our BQ schema
        allowed_cols = [
            "id", "name", "type", "date", "duration_sec", 
            "distance_m", "avg_hr", "max_hr", "avg_pace", 
            "calories", "elevation_gain", "vo2max", "avg_power"
        ]
        # Only keep columns that are both in allowed_cols and the dataframe
        cols_to_keep = [c for c in allowed_cols if c in df_act.columns]
        df_act = df_act[cols_to_keep].copy()
        
        # 3. Force numeric types for FLOAT64 columns in BQ
        float_cols = [
            "duration_sec", "distance_m", "avg_hr", "max_hr", 
            "avg_pace", "calories", "elevation_gain", "vo2max", "avg_power"
        ]
        for col in float_cols:
            if col in df_act.columns:
                df_act[col] = pd.to_numeric(df_act[col], errors="coerce").astype(float)
        
        log.info(f"Upserting {len(df_act)} activity summaries...")
        upsert_to_bq(df_act, "recent_activities", unique_key="id")

if __name__ == "__main__":
    # Range covering April 23 and 25, 2025
    manual_import(date(2025, 4, 20), date(2025, 4, 30))
