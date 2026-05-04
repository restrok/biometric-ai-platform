import os
from google.cloud import bigquery
from src.utils.config import setup_environment

setup_environment()
client = bigquery.Client()
project = os.getenv("GOOGLE_CLOUD_PROJECT")
dataset = os.getenv("DATASET_NAME", "biometric_data_dev")

ids = ["18916955905", "18935473640", "18935474486"]
ids_str = ", ".join([f"'{i}'" for i in ids])

print(f"--- Checking metadata for activities in {dataset} ---")
query_meta = f"SELECT id, date, name, type, distance_m, avg_hr FROM `{project}.{dataset}.recent_activities` WHERE CAST(id AS STRING) IN ({ids_str})"
rows_meta = list(client.query(query_meta).result())
for r in rows_meta:
    print(dict(r))

print(f"\n--- Checking telemetry (ticks) for these IDs ---")
query_tel = f"SELECT activity_id, count(*) as tick_count FROM `{project}.{dataset}.latest_activity_telemetry` WHERE activity_id IN ({ids_str}) GROUP BY activity_id"
rows_tel = list(client.query(query_tel).result())
for r in rows_tel:
    print(dict(r))
