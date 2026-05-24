import asyncio
import json
from google.cloud import bigquery
from src.utils.config import get_config, setup_environment

def run():
    setup_environment()
    config = get_config()
    pid = config['project_id']
    ds = config['dataset_id']
    client = bigquery.Client(project=pid)
    
    sql = f"""
    WITH daily_load AS (
        SELECT 
            DATE(TIMESTAMP_MICROS(CAST(date / 1000 AS INT64))) as run_date, 
            SUM(distance_m)/1000 as distance_km, 
            AVG(avg_power / NULLIF(avg_hr, 0)) as efficiency 
        FROM  
        WHERE user_id = 'fsirio' AND type = 'running' 
        GROUP BY 1
    ),
    rolling_load AS (
        SELECT 
            run_date, 
            distance_km, 
            efficiency,
            SUM(distance_km) OVER (ORDER BY run_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as acute_load,
            SUM(distance_km) OVER (ORDER BY run_date ROWS BETWEEN 27 PRECEDING AND CURRENT ROW) / 4 as chronic_load
        FROM daily_load
    )
    SELECT 
        run_date, 
        ROUND(acute_load, 1) as acute,
        ROUND(chronic_load, 1) as chronic,
        ROUND(acute_load / NULLIF(chronic_load, 0), 2) as ac_ratio, 
        ROUND(efficiency, 2) as eff, 
        h.fatigue_level, 
        h.feeling 
    FROM rolling_load r 
    LEFT JOIN user_health_status h ON r.run_date = h.date 
    WHERE r.acute_load / NULLIF(chronic_load, 0) > 1.3 
    ORDER BY run_date DESC 
    LIMIT 100
    """
    
    query_job = client.query(sql)
    results = [dict(row) for row in query_job.result()]
    print(json.dumps(results, default=str))

if __name__ == '__main__':
    run()
