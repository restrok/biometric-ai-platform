"""Audits Event-Based Telemetry Architecture for precision."""

import json
import logging
import os
import sys
from typing import Any

import numpy as np
import pandas as pd
from google.cloud import bigquery

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def audit_telemetry_precision(
    activity_id: str | None = None,
    user_id: str = "fsirio",
    json_path: str | None = None,
) -> None:
    """Audits the current Event-Based Telemetry Architecture.

    Compares the 'Coach View' (15s aggregated + segmented) against the
    'Ground Truth' (1s raw data).

    Args:
        activity_id: The unique ID of the activity to analyze.
        user_id: The ID of the user.
        json_path: Optional path to a local JSON file containing raw data.
    """
    if json_path:
        log.info(f"Loading raw data from local JSON: {json_path}")
        with open(json_path) as f:
            raw_data = json.load(f)
        df_raw = pd.DataFrame(raw_data)
        activity_name = f"JSON:{os.path.basename(json_path)}"
    else:
        log.info(f"Fetching raw data from BigQuery for activity: {activity_id or 'latest'}")
        from src.utils.config import setup_environment

        setup_environment()
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        dataset = "biometric_data_dev"
        client = bigquery.Client()

        if not activity_id:
            query_act = (
                f"SELECT id, name FROM `{project_id}.{dataset}.recent_activities` "
                f"WHERE user_id = '{user_id}' AND type = 'running' "
                f"ORDER BY date DESC LIMIT 1"
            )
            res = list(client.query(query_act).result())
            if not res:
                log.info("No activities found.")
                return
            activity_id, activity_name = res[0].id, res[0].name
        else:
            activity_name = f"ID:{activity_id}"

        query_raw = f"""
            SELECT 
                timestamp_ms, hr_bpm, power_w, cadence_spm, stride_length_mm, 
                vertical_oscillation_cm, ground_contact_time_ms, vertical_ratio, 
                vertical_speed, body_battery, temperature_c, elevation_m, 
                speed_mps, gap_mps, performance_condition, run_walk_index
            FROM `{project_id}.{dataset}.latest_activity_telemetry` 
            WHERE activity_id = '{activity_id}' 
            ORDER BY timestamp_ms
        """
        df_raw = client.query(query_raw).to_dataframe()

    df_raw["dt"] = pd.to_datetime(df_raw["timestamp_ms"], unit="ms")

    # 1. Simulate 15s Aggregation (Retriever Logic)
    df_raw["time_block_15s"] = df_raw["dt"].dt.floor("15s")

    # We audit all these metrics
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

    # 2. Simulate Event-Based Segmentation (Work Thresholds: >180W or >145spm)
    pwr_col = "power_w" if "power_w" in raw_15s.columns else None
    cad_col = "cadence_spm" if "cadence_spm" in raw_15s.columns else None

    if pwr_col and cad_col:
        raw_15s["is_work"] = ((raw_15s[pwr_col] > 180) | (raw_15s[cad_col] > 145)).astype(int)
    else:
        raw_15s["is_work"] = 1  # Fallback

    # 5-min limit logic
    raw_15s["time_bucket"] = raw_15s["time_block_15s"].astype(np.int64) // 10**9 // 300
    raw_15s["change"] = (
        (raw_15s["is_work"].diff().fillna(0).abs() > 0) | (raw_15s["time_bucket"].diff().fillna(0).abs() > 0)
    ).astype(int)
    raw_15s["segment_id"] = raw_15s["change"].cumsum()

    # 3. Final Comparison Table
    final_segments = (
        raw_15s.groupby("segment_id")
        .agg(
            {
                "time_block_15s": ["min", "max"],
                "is_work": "first",
                **{
                    c: "mean"
                    for c in raw_15s.columns
                    if c
                    not in [
                        "time_block_15s",
                        "is_work",
                        "time_bucket",
                        "change",
                        "segment_id",
                    ]
                },
            }
        )
        .reset_index()
    )

    # Flatten and cleanup
    final_segments.columns = [
        c[0] if c[1] in ["", "first", "mean"] else f"{c[0]}_{c[1]}" for c in final_segments.columns
    ]
    final_segments["dur"] = (
        final_segments["time_block_15s_max"] - final_segments["time_block_15s_min"]
    ).dt.total_seconds() + 15

    log.info(f"### 📊 AUDIT FOR: {activity_name}")
    log.info("Format: [Coach Aggregated] | [Real Raw Mean] | Delta %")
    log.info("-" * 120)

    for _, seg in final_segments[final_segments["dur"] >= 10].iterrows():
        mask = (df_raw["dt"] >= seg["time_block_15s_min"]) & (
            df_raw["dt"] <= (seg["time_block_15s_max"] + pd.Timedelta(seconds=14.9))
        )
        gt = df_raw[mask]

        type_str = "WORK" if seg["is_work"] else "REST"
        log.info(f"{type_str} [{int(seg['dur'])}s]:")

        for c in ["power_w", "hr_bpm", "body_battery", "stride_length_mm"]:
            if c in gt.columns:
                val_agg = seg[c]
                val_raw = gt[c].mean()
                drift = ((val_agg - val_raw) / val_raw * 100) if val_raw != 0 else 0
                log.info(f"  - {c:<18}: {val_agg:>7.1f} | {val_raw:>7.1f} | {drift:>6.2f}%")

        # Check MAXes
        if "power_w_max" in seg:
            log.info(f"  - POWER MAX         : {seg['power_w_max']:>7.1f} | {gt['power_w'].max():>7.1f} | 0.00%")
        if "hr_bpm_max" in seg:
            log.info(f"  - HR MAX            : {seg['hr_bpm_max']:>7.1f} | {gt['hr_bpm'].max():>7.1f} | 0.00%")

    log.info("-" * 120)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg and arg.endswith(".json"):
        audit_telemetry_precision(json_path=arg)
    else:
        audit_telemetry_precision(activity_id=arg)
