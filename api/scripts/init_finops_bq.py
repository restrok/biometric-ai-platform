import os
from google.cloud import bigquery
from pathlib import Path
from dotenv import load_dotenv

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
DATASET_ID = "biometric_data_dev"
TABLE_ID = "finops_logs"

def init_finops_bq():
    print("🚀 Initializing FinOps BigQuery Table...")
    client = bigquery.Client(project=PROJECT_ID)
    
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    
    schema = [
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("request_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("model", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("input_tokens", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("output_tokens", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("total_tokens", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("cost_usd", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("latency_ms", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("node_name", "STRING", mode="NULLABLE"),
    ]
    
    table = bigquery.Table(table_ref, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="timestamp"
    )
    
    try:
        client.create_table(table, exists_ok=True)
        print(f"✅ Table {table_ref} created and partitioned by day.")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    init_finops_bq()
