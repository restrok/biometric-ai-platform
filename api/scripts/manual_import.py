"""Script for manual activity import from Garmin to BigQuery."""

import logging
import os
from datetime import date
from typing import Optional

import pandas as pd
from google.cloud import bigquery

from src.tools.etl_job import upload_to_bq, upsert_to_bq
from src.utils.provider_factory import get_provider

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def manual_import(start_date: date, end_date: date) -> None:
    """Manually fetches and imports activities for a given date range.

    Args:
        start_date: Start date for the import range.
        end_date: End date for the import range.
    """
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

            # Ensure types for BQ for any newly added fields
            float_fields = [
                "run_walk_index",
                "body_battery",
                "vertical_speed",
                "vertical_ratio",
                "performance_condition",
                "gap_mps",
                "fractional_cadence",
                "stride_length_mm",
                "vertical_oscillation_cm",
                "ground_contact_time_ms",
                "temperature_c",
            ]
            for field in float_fields:
                if field in df_t.columns:
                    df_t[field] = pd.to_numeric(df_t[field], errors="coerce").astype(
                        float
                    )

            log.info(f"Uploading {len(df_t)} telemetry ticks...")
            client = bigquery.Client()
            proj = os.getenv("GOOGLE_CLOUD_PROJECT")
            ds = os.getenv("DATASET_NAME", "biometric_data_dev")
            client.query(
                f"DELETE FROM `{proj}.{ds}.latest_activity_telemetry` "
                f"WHERE activity_id = '{act.id}'"
            ).result()
            upload_to_bq(df_t, "latest_activity_telemetry", "telemetry")

            # Calculate avg/max power if available
            avg_pwr = None
            max_pwr = None
            if "power_w" in df_t.columns:
                valid_pwr = df_t[df_t["power_w"] > 0]["power_w"]
                if not valid_pwr.empty:
                    avg_pwr = float(valid_pwr.mean())
                    max_pwr = float(valid_pwr.max())

            summary = act.model_dump()
            summary["avg_power"] = avg_pwr
            if max_pwr is not None:
                summary["max_power"] = max_pwr
            activity_summaries.append(summary)

    if activity_summaries:
        df_act = pd.DataFrame(activity_summaries)

        # 1. Convert date to nanoseconds (int64) to match BQ schema
        df_act["date"] = pd.to_datetime(df_act["date"]).astype(int)

        # 2. Filter for only the columns supported by our BQ schema
        allowed_cols = [
            "id",
            "name",
            "type",
            "date",
            "duration_sec",
            "distance_m",
            "avg_hr",
            "max_hr",
            "avg_pace",
            "calories",
            "elevation_gain",
            "vo2max",
            "avg_power",
            "max_power",
            "normalized_power",
            "avg_cadence",
            "max_cadence",
            "user_id",
        ]
        # Only keep columns that are both in allowed_cols and the dataframe
        cols_to_keep = [c for c in allowed_cols if c in df_act.columns]
        df_act = df_act[cols_to_keep].copy()

        # 3. Force numeric types for FLOAT64 columns in BQ
        float_cols = [
            "duration_sec",
            "distance_m",
            "avg_hr",
            "max_hr",
            "avg_pace",
            "calories",
            "elevation_gain",
            "vo2max",
            "avg_power",
            "max_power",
            "normalized_power",
            "avg_cadence",
            "max_cadence",
        ]
        for col in float_cols:
            if col in df_act.columns:
                df_act[col] = pd.to_numeric(df_act[col], errors="coerce").astype(float)

        log.info(f"Upserting {len(df_act)} activity summaries...")
        upsert_to_bq(df_act, "recent_activities", unique_key="id")


if __name__ == "__main__":
    # Range covering April 23 and 25, 2025
    manual_import(date(2025, 4, 20), date(2025, 4, 30))
