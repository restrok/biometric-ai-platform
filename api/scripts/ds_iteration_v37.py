import asyncio
import json
import logging
import os
from google.cloud import bigquery
from src.tools.data_scientist import execute_exploratory_query, execute_exploratory_query_dry_run

logging.basicConfig(level=logging.INFO)

async def iterate_methodology():
    user_id = 'fsirio'
    latest_id = '22946951415'
    pid = 'bio-intelligence-dev'
    ds = 'biometric_data_dev'
    
    # Use standard BigQuery identifiers where possible or escape dots differently
    # Standard way to refer to tables in BQ without backticks: project_id.dataset_id.table_id
    # (actually BQ usually likes backticks if dots are involved, but we can try without if the identifiers are simple)
    # Actually, BQ allows backticks, we just need to avoid the SHELL seeing them.
    
    query_compare = f"""
    WITH base AS (
        SELECT 
            t.activity_id, t.timestamp_ms, t.hr_bpm, t.power_w,
            CASE WHEN t.power_w > 180 OR t.hr_bpm > p.custom_z1_max THEN 1 ELSE 0 END as is_work
        FROM `{pid}.{ds}.latest_activity_telemetry` t
        JOIN `{pid}.{ds}.user_profile` p ON t.user_id = p.user_id
        WHERE t.activity_id = '{latest_id}' AND t.user_id = '{user_id}'
    ),
    state_changes AS (
        SELECT activity_id, timestamp_ms, hr_bpm, power_w, is_work,
            CASE WHEN is_work != LAG(is_work) OVER (ORDER BY timestamp_ms) THEN 1 ELSE 0 END as state_change
        FROM base
    ),
    segments AS (
        SELECT activity_id, timestamp_ms, hr_bpm, power_w, is_work,
            SUM(state_change) OVER (ORDER BY timestamp_ms) as event_id
        FROM state_changes
    ),
    segment_stats AS (
        SELECT 
            event_id, is_work,
            MIN(timestamp_ms) as start_ms,
            MAX(timestamp_ms) as end_ms,
            (MAX(timestamp_ms) - MIN(timestamp_ms)) / 1000 as duration_sec
        FROM segments
        GROUP BY 1, 2
        HAVING duration_sec > 300
    ),
    window_comparison AS (
        SELECT 
            s.event_id, s.is_work, s.duration_sec,
            -- V3.6 (10% Fractional)
            AVG(CASE WHEN t.timestamp_ms <= s.start_ms + (s.duration_sec * 100) THEN t.hr_bpm END) as hr_start_10pct,
            -- V3.7 (30s)
            AVG(CASE WHEN t.timestamp_ms <= s.start_ms + 30000 THEN t.hr_bpm END) as hr_start_30s,
            -- V3.8 (15s)
            AVG(CASE WHEN t.timestamp_ms <= s.start_ms + 15000 THEN t.hr_bpm END) as hr_start_15s,
            
            -- Stability check (Standard Deviation in windows)
            STDDEV(CASE WHEN t.timestamp_ms <= s.start_ms + (s.duration_sec * 100) THEN t.hr_bpm END) as hr_std_10pct,
            STDDEV(CASE WHEN t.timestamp_ms <= s.start_ms + 30000 THEN t.hr_bpm END) as hr_std_30s,
            STDDEV(CASE WHEN t.timestamp_ms <= s.start_ms + 15000 THEN t.hr_bpm END) as hr_std_15s
        FROM segment_stats s
        JOIN segments t ON s.event_id = t.event_id
        GROUP BY 1, 2, 3
    )
    SELECT event_id, is_work, duration_sec, hr_start_10pct, hr_start_30s, hr_start_15s, hr_std_10pct, hr_std_30s, hr_std_15s
    FROM window_comparison 
    LIMIT 5
    """
    
    # Cost check
    dry_run = execute_exploratory_query_dry_run.invoke({'sql': query_compare, 'user_id': user_id})
    print(f"DRY_RUN_RESULT:{dry_run}")
    
    # Actual execution
    results = execute_exploratory_query.invoke({'sql': query_compare, 'user_id': user_id})
    print(f"QUERY_RESULTS:{results}")

if __name__ == '__main__':
    asyncio.run(iterate_methodology())
