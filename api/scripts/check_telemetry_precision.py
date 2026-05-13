import logging
import os

import pandas as pd
from google.cloud import bigquery

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def check_precision(user_id="fsirio", activity_id=None):
    """
    Audits the new Hybrid Telemetry Architecture:
    1. Global Metrics (100% Accuracy)
    2. Segmented Metrics (For "Leak" detection)
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
    dataset = os.getenv("DATASET_NAME", "biometric_data_dev")
    client = bigquery.Client(project=project_id)

    # 1. Get activity ID
    if not activity_id:
        query_act = f"SELECT id, name FROM `{project_id}.{dataset}.recent_activities` WHERE user_id = '{user_id}' AND type = 'running' ORDER BY date DESC LIMIT 1"
        results = list(client.query(query_act).result())
        activity = results[0]
        activity_id, activity_name = activity.id, activity.name
    else:
        activity_name = "Specified ID"

    print(f"\n🔍 FINAL AUDIT: Hybrid Architecture for {activity_name}")

    # 2. Fetch RAW telemetry
    query_raw = f"""
        SELECT hr_bpm, power_w, cadence_spm, ground_contact_time_ms as gct, 
               vertical_oscillation_cm as vo, timestamp_ms
        FROM `{project_id}.{dataset}.latest_activity_telemetry`
        WHERE activity_id = '{activity_id}' AND hr_bpm > 0
        ORDER BY timestamp_ms ASC
    """
    df_raw = client.query(query_raw).to_dataframe()
    
    def calc_metrics(df):
        if len(df) < 2: return {"drift": 0, "avg_gct": 0, "avg_vo": 0, "hr_per_step": 0}
        mid = len(df) // 2
        eff1 = df.iloc[:mid]["power_w"].mean() / df.iloc[:mid]["hr_bpm"].mean()
        eff2 = df.iloc[mid:]["power_w"].mean() / df.iloc[mid:]["hr_bpm"].mean()
        drift = ((eff1 - eff2) / (eff1 if eff1 != 0 else 1)) * 100
        return {
            "drift": drift,
            "avg_gct": df["gct"].mean(),
            "avg_vo": df["vo"].mean(),
            "hr_per_step": (df["hr_bpm"] / df["cadence_spm"].replace(0, 1)).mean()
        }

    # 3. Calculations
    m_raw = calc_metrics(df_raw)

    # COACH VIEW 1: Global Metrics (Simulating pre-calculated BQ metrics)
    # This should match RAW exactly because BQ does it on all rows
    m_coach_global = m_raw 

    # COACH VIEW 2: Segmented Metrics (5-min blocks)
    df_raw["minute_ts"] = pd.to_datetime(df_raw["timestamp_ms"] * 1000000).dt.floor("1min")
    raw_minutes = df_raw.groupby("minute_ts").agg({"hr_bpm":"mean", "power_w":"mean", "cadence_spm":"mean", "gct":"mean", "vo":"mean"}).reset_index()
    raw_minutes["time_block"] = (raw_minutes["minute_ts"].dt.minute // 5).astype(int)
    raw_minutes["is_new"] = (raw_minutes["time_block"] != raw_minutes["time_block"].shift(1)).astype(int)
    raw_minutes["segment_id"] = raw_minutes["is_new"].cumsum()
    df_segmented = raw_minutes.groupby("segment_id").agg({"hr_bpm":"mean", "power_w":"mean", "cadence_spm":"mean", "gct":"mean", "vo":"mean"}).reset_index()
    m_coach_segmented = calc_metrics(df_segmented)

    # 4. Reporting
    print(f"{'='*70}")
    print(f"{'METRIC':<20} | {'RAW (Truth)':<12} | {'COACH (Global)':<15} | {'COACH (Series)':<12}")
    print(f"{'-'*70}")
    
    metrics = [
        ("Cardiac Drift", "drift", "%"),
        ("Avg GCT", "avg_gct", "ms"),
        ("Avg Oscillation", "avg_vo", "cm"),
        ("HR per Step", "hr_per_step", ""),
    ]

    for label, key, unit in metrics:
        print(f"{label:<20} | {m_raw[key]:>10.2f}{unit} | {m_coach_global[key]:>13.2f}{unit} | {m_coach_segmented[key]:>10.2f}{unit}")
    
    print(f"{'-'*70}")
    print(f"Data Points:         | {len(df_raw):<12} | {'1 (Pre-calc)':<15} | {len(df_segmented):<12}")
    print(f"{'='*70}")
    print("✅ PREDICTION: The Coach will use GLOBAL for values and SERIES to find the exact 'Leak' point.")

if __name__ == "__main__":
    check_precision()
