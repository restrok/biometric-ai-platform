import os

import numpy as np
import pandas as pd
from google.cloud import bigquery
from typing import Any

from src.utils.config import setup_environment


def main():
    setup_environment()
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    dataset = "biometric_data_dev"
    client = bigquery.Client()

    query_raw = f"""
        SELECT 
            timestamp_ms, hr_bpm, power_w, cadence_spm, stride_length_mm, 
            vertical_oscillation_cm, ground_contact_time_ms, vertical_ratio, 
            vertical_speed, body_battery, temperature_c, elevation_m, 
            speed_mps, gap_mps, performance_condition, run_walk_index
        FROM `{project_id}.{dataset}.latest_activity_telemetry` 
        WHERE activity_id = '23239685122' 
        ORDER BY timestamp_ms
    """
    df_raw = client.query(query_raw).to_dataframe()
    df_raw["dt"] = pd.to_datetime(df_raw["timestamp_ms"], unit="ms")
    df_raw["time_block_15s"] = df_raw["dt"].dt.floor("15s")

    cols = [
        "hr_bpm",
        "power_w",
        "cadence_spm",
        "stride_length_mm",
        "vertical_oscillation_cm",
        "ground_contact_time_ms",
        "vertical_ratio",
        "body_battery",
        "temperature_c",
        "elevation_m",
    ]
    agg_map: dict[str, Any] = {c: "mean" for c in cols if c in df_raw.columns}
    agg_map.update({"hr_bpm": ["mean", "max"], "power_w": ["mean", "max"]})

    raw_15s = df_raw.groupby("time_block_15s").agg(agg_map)
    raw_15s.columns = [f"{c[0]}_{c[1]}" if isinstance(c, tuple) and c[1] != "mean" else c[0] for c in raw_15s.columns]
    raw_15s = raw_15s.reset_index()

    raw_15s["is_work"] = ((raw_15s["power_w"] > 180) | (raw_15s["cadence_spm"] > 145)).astype(int)
    raw_15s["time_bucket"] = raw_15s["time_block_15s"].astype(np.int64) // 10**9 // 300

    # Calculate difference
    raw_15s["is_work_diff"] = raw_15s["is_work"].diff().fillna(0).abs()
    raw_15s["time_bucket_diff"] = raw_15s["time_bucket"].diff().fillna(0).abs()

    raw_15s["change"] = ((raw_15s["is_work_diff"] > 0) | (raw_15s["time_bucket_diff"] > 0)).astype(int)
    raw_15s["segment_id"] = raw_15s["change"].cumsum()

    print("Columns in raw_15s:")
    print(raw_15s.columns.tolist())
    print("\nFirst 15 rows of segmentation calculation:")
    print(
        raw_15s[
            ["time_block_15s", "is_work", "time_bucket", "is_work_diff", "time_bucket_diff", "change", "segment_id"]
        ].head(15)
    )
    print("\nRows around segment changes:")
    print(raw_15s[raw_15s["change"] > 0][["time_block_15s", "is_work", "time_bucket", "change", "segment_id"]].head(15))


if __name__ == "__main__":
    main()
