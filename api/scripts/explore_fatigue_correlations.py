from google.cloud import bigquery

from src.utils.config import get_config, setup_environment


def run_analysis():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]
    user_id = 'fsirio'

    query = f"""
    WITH telemetry_base AS (
        SELECT 
            activity_id,
            timestamp_ms,
            hr_bpm, 
            power_w, 
            ground_contact_time_ms as gct,
            PERCENT_RANK() OVER(PARTITION BY activity_id ORDER BY timestamp_ms) as total_progress
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry`
        WHERE user_id = '{user_id}'
        AND hr_bpm > 0
    ),
    telemetry_stats AS (
        SELECT 
            activity_id, hr_bpm, power_w, gct,
            PERCENT_RANK() OVER(PARTITION BY activity_id ORDER BY timestamp_ms) as progress
        FROM telemetry_base
        WHERE total_progress >= 0.15 AND total_progress <= 0.95 -- Exclude warmup/cooldown
    ),
    activity_metrics AS (
        SELECT
            activity_id,
            AVG(CASE WHEN progress < 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_first_half,
            AVG(CASE WHEN progress >= 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_second_half,
            AVG(CASE WHEN progress < 0.5 THEN gct END) as gct_first_half,
            AVG(CASE WHEN progress >= 0.5 THEN gct END) as gct_second_half
        FROM telemetry_stats
        GROUP BY activity_id
    ),
    drift_calculations AS (
        SELECT
            activity_id,
            ((eff_first_half - eff_second_half) / NULLIF(eff_first_half, 0)) * 100 as decoupling_pct,
            ((gct_second_half - gct_first_half) / NULLIF(gct_first_half, 0)) * 100 as gct_drift_pct
        FROM activity_metrics
        WHERE eff_first_half IS NOT NULL AND eff_second_half IS NOT NULL
        AND gct_first_half IS NOT NULL AND gct_second_half IS NOT NULL
    ),
    activity_dates AS (
        SELECT CAST(id AS STRING) as activity_id, DATE(TIMESTAMP_SECONDS(date)) as activity_date, name as activity_name
        FROM `{config["project_id"]}.{dataset}.recent_activities`
        WHERE user_id = '{user_id}'
    ),
    hrv_data AS (
        SELECT 
            CAST(date AS DATE) as hrv_date, 
            avg_hrv
        FROM `{config["project_id"]}.{dataset}.hrv_history`
        WHERE user_id = '{user_id}'
    ),
    merged_data AS (
        SELECT 
            d.activity_id,
            ad.activity_name,
            ad.activity_date,
            d.decoupling_pct,
            d.gct_drift_pct,
            h.avg_hrv as next_day_hrv
        FROM drift_calculations d
        JOIN activity_dates ad ON d.activity_id = ad.activity_id
        JOIN hrv_data h ON h.hrv_date = DATE_ADD(ad.activity_date, INTERVAL 1 DAY)
    )
    SELECT * FROM merged_data ORDER BY activity_date DESC
    """
    
    print(f"Running query for user {user_id}...")
    try:
        query_job = client.query(query)
        results = list(query_job.result())
    except Exception as e:
        print(f"Error running query: {e}")
        return
    
    if not results:
        print("No correlations found. (Maybe lack of matching HRV data for the day after the activity?)")
        return

    print(f"{'Date':<12} | {'Activity':<30} | {'Decoupling':<10} | {'GCT Drift':<10} | {'Next HRV':<8}")
    print("-" * 85)
    for row in results:
        name = (row.activity_name[:30] if row.activity_name else "Unknown")
        dec = row.decoupling_pct if row.decoupling_pct is not None else 0.0
        drift = row.gct_drift_pct if row.gct_drift_pct is not None else 0.0
        hrv = row.next_day_hrv if row.next_day_hrv is not None else 0.0
        print(f"{str(row.activity_date):<12} | {name:<30} | {dec:>9.2f}% | {drift:>9.2f}% | {hrv:>8.1f}")

    # Summary analysis
    print("\nSummary Analysis (HRV the day after):")
    
    # Filter results that have HRV data
    valid_results = [r for r in results if r.next_day_hrv is not None]
    
    if not valid_results:
        print("No valid data points with next-day HRV found for summary.")
        return

    # Bucket by GCT Drift
    gct_buckets = [
        ("GCT Drift < 2%", [r for r in valid_results if r.gct_drift_pct < 2]),
        ("GCT Drift 2-5%", [r for r in valid_results if 2 <= r.gct_drift_pct < 5]),
        ("GCT Drift > 5%", [r for r in valid_results if r.gct_drift_pct >= 5]),
    ]
    
    print("\n[GCT Drift Correlation]")
    for label, group in gct_buckets:
        if group:
            avg_hrv = sum(r.next_day_hrv for r in group) / len(group)
            print(f"- {label:<20}: Avg HRV = {avg_hrv:.1f} (n={len(group)})")
        else:
            print(f"- {label:<20}: No data")

    # Bucket by Decoupling
    dec_buckets = [
        ("Decoupling < 5%", [r for r in valid_results if r.decoupling_pct < 5]),
        ("Decoupling 5-10%", [r for r in valid_results if 5 <= r.decoupling_pct < 10]),
        ("Decoupling > 10%", [r for r in valid_results if r.decoupling_pct >= 10]),
    ]
    
    print("\n[Aerobic Decoupling Correlation]")
    for label, group in dec_buckets:
        if group:
            avg_hrv = sum(r.next_day_hrv for r in group) / len(group)
            print(f"- {label:<20}: Avg HRV = {avg_hrv:.1f} (n={len(group)})")
        else:
            print(f"- {label:<20}: No data")

if __name__ == "__main__":
    run_analysis()
