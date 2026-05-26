import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
DATASET_ID = os.getenv("DATASET_ID", "biometric_data_dev")
USER_ID = "fsirio"

def compare_v3_v4_v35():
    client = bigquery.Client(project=PROJECT_ID)
    
    # 1. Get the latest activity ID for the user
    query_latest = f"""
        SELECT activity_id 
        FROM `{PROJECT_ID}.{DATASET_ID}.latest_activity_telemetry` 
        WHERE user_id = '{USER_ID}' 
        GROUP BY activity_id 
        ORDER BY MAX(timestamp_ms) DESC 
        LIMIT 1
    """
    latest_id = list(client.query(query_latest).result())[0].activity_id
    log.info(f"🔍 Comparing V3 vs V4 vs V3.5 for activity: {latest_id}\n")

    # --- V3 Methodology (Current) ---
    query_v3 = f"""
    WITH raw_15s AS (
        SELECT 
            activity_id,
            TIMESTAMP_SECONDS(CAST(FLOOR(timestamp_ms / 15000) * 15 AS INT64)) as time_block,
            AVG(hr_bpm) as hr,
            AVG(power_w) as pwr,
            AVG(cadence_spm) as cad
        FROM `{PROJECT_ID}.{DATASET_ID}.latest_activity_telemetry`
        WHERE activity_id = '{latest_id}' AND user_id = '{USER_ID}'
        GROUP BY 1, 2
    ),
    classified AS (
        SELECT activity_id, time_block, hr, pwr, cad,
            CASE WHEN pwr > 180 OR cad > 145 THEN 1 ELSE 0 END as is_work,
            CAST(FLOOR(UNIX_SECONDS(time_block) / 300) AS INT64) as time_bucket
        FROM raw_15s
    ),
    state_changes AS (
        SELECT activity_id, time_block, hr, pwr, cad, is_work, time_bucket,
            CASE 
                WHEN is_work != LAG(is_work) OVER(ORDER BY time_block) THEN 1 
                WHEN time_bucket != LAG(time_bucket) OVER(ORDER BY time_block) THEN 1
                ELSE 0 
            END as state_change
        FROM classified
    ),
    segments AS (
        SELECT is_work, time_block, hr, pwr,
            SUM(state_change) OVER(ORDER BY time_block) as segment_id
        FROM state_changes
    )
    SELECT 
        is_work,
        MIN(time_block) as start_time,
        COUNT(*) * 15 as duration_sec,
        AVG(hr) as avg_hr,
        AVG(pwr) as avg_pwr
    FROM segments
    GROUP BY is_work, segment_id
    HAVING duration_sec >= 10
    ORDER BY start_time ASC
    """

    # --- V4 Methodology (Proposed by DS) ---
    query_v4 = f"""
    WITH base AS (
      SELECT 
        t.activity_id, 
        t.timestamp_ms, 
        t.hr_bpm, 
        t.power_w,
        CASE WHEN t.hr_bpm > p.custom_z2_max THEN 1 ELSE 0 END as state
      FROM `{PROJECT_ID}.{DATASET_ID}.latest_activity_telemetry` t
      JOIN `{PROJECT_ID}.{DATASET_ID}.user_profile` p ON t.user_id = p.user_id
      WHERE t.user_id = '{USER_ID}'
      AND t.activity_id = '{latest_id}'
    ),
    statechanges AS (
      SELECT activity_id, timestamp_ms, hr_bpm, power_w, state,
        LAG(state) OVER (ORDER BY timestamp_ms) as prevstate
      FROM base
    ),
    eventids AS (
      SELECT timestamp_ms, hr_bpm, power_w, state,
        SUM(CASE WHEN state != prevstate THEN 1 ELSE 0 END) OVER (ORDER BY timestamp_ms) as eventid
      FROM statechanges
    )
    SELECT 
      state as is_work, 
      MIN(timestamp_ms) as start_time_ms, 
      AVG(hr_bpm) as avg_hr, 
      AVG(power_w) as avg_pwr,
      (MAX(timestamp_ms) - MIN(timestamp_ms)) / 1000 as duration_sec
    FROM eventids
    GROUP BY eventid, state
    ORDER BY start_time_ms
    """

    # --- V3.5 Methodology (Hybrid Proposal) ---
    query_v35 = f"""
    WITH raw_15s AS (
        SELECT 
            t.activity_id,
            TIMESTAMP_SECONDS(CAST(FLOOR(t.timestamp_ms / 15000) * 15 AS INT64)) as time_block,
            AVG(t.hr_bpm) as hr,
            AVG(t.power_w) as pwr,
            AVG(t.cadence_spm) as cad,
            ANY_VALUE(p.custom_z2_max) as z2_max
        FROM `{PROJECT_ID}.{DATASET_ID}.latest_activity_telemetry` t
        JOIN `{PROJECT_ID}.{DATASET_ID}.user_profile` p ON t.user_id = p.user_id
        WHERE t.activity_id = '{latest_id}' AND t.user_id = '{USER_ID}'
        GROUP BY 1, 2
    ),
    classified AS (
        SELECT time_block, hr, pwr, z2_max,
            CASE WHEN pwr > 180 OR hr > z2_max THEN 1 ELSE 0 END as is_work
        FROM raw_15s
    ),
    state_changes AS (
        SELECT hr, pwr, is_work, time_block,
            CASE WHEN is_work != LAG(is_work) OVER(ORDER BY time_block) THEN 1 ELSE 0 END as state_change
        FROM classified
    ),
    segments AS (
        SELECT is_work, time_block, hr, pwr,
            SUM(state_change) OVER(ORDER BY time_block) as segment_id
        FROM state_changes
    )
    SELECT 
        is_work,
        MIN(time_block) as start_time,
        COUNT(*) * 15 as duration_sec,
        AVG(hr) as avg_hr,
        AVG(pwr) as avg_pwr
    FROM segments
    GROUP BY is_work, segment_id
    HAVING duration_sec >= 10
    ORDER BY start_time ASC
    """

    # Execute and Compare
    rows_v3 = list(client.query(query_v3).result())
    rows_v4 = list(client.query(query_v4).result())
    rows_v35 = list(client.query(query_v35).result())

    log.info("📊 --- RESULTS COMPARISON ---")
    log.info(f"{'Metric':<20} | {'V3 (Current)':<15} | {'V4 (DS)':<15} | {'V3.5 (Hybrid)':<15}")
    log.info("-" * 75)
    log.info(f"{'Total Segments':<20} | {len(rows_v3):<15} | {len(rows_v4):<15} | {len(rows_v35):<15}")
    
    total_dur_v3 = sum(r.duration_sec for r in rows_v3)
    total_dur_v4 = sum(r.duration_sec for r in rows_v4)
    total_dur_v35 = sum(r.duration_sec for r in rows_v35)
    log.info(f"{'Total Duration (s)':<20} | {total_dur_v3:<15.0f} | {total_dur_v4:<15.0f} | {total_dur_v35:<15.0f}")
    
    avg_seg_v3 = total_dur_v3 / len(rows_v3) if rows_v3 else 0
    avg_seg_v4 = total_dur_v4 / len(rows_v4) if rows_v4 else 0
    avg_seg_v35 = total_dur_v35 / len(rows_v35) if rows_v35 else 0
    log.info(f"{'Avg Segment Len (s)':<20} | {avg_seg_v3:<15.1f} | {avg_seg_v4:<15.1f} | {avg_seg_v35:<15.1f}")
    
    log.info("\n📝 --- SAMPLE SEGMENTS (V3) ---")
    for r in rows_v3[:3]:
        status = "WORK" if r.is_work else "REST"
        log.info(f"  {status}: {r.duration_sec:>4.0f}s | HR: {r.avg_hr:>5.1f} | PWR: {r.avg_pwr:>5.1f}W")
        
    log.info("\n🚀 --- SAMPLE SEGMENTS (V4) ---")
    for r in rows_v4[:1]:
        status = "WORK" if r.is_work else "REST"
        log.info(f"  {status}: {r.duration_sec:>4.0f}s | HR: {r.avg_hr:>5.1f} | PWR: {r.avg_pwr:>5.1f}W")

    log.info("\n💎 --- SAMPLE SEGMENTS (V3.5 Hybrid) ---")
    for r in rows_v35[:5]:
        status = "WORK" if r.is_work else "REST"
        log.info(f"  {status}: {r.duration_sec:>4.0f}s | HR: {r.avg_hr:>5.1f} | PWR: {r.avg_pwr:>5.1f}W")

if __name__ == "__main__":
    compare_v3_v4_v35()
