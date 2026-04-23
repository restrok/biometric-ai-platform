import os
from google.cloud import bigquery
from pathlib import Path
from dotenv import load_dotenv

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DATASET_ID = "biometric_data_dev"

def create_profile_tables():
    client = bigquery.Client(project=PROJECT_ID)
    
    # 1. User Profile Table
    profile_table_id = f"{PROJECT_ID}.{DATASET_ID}.user_profile"
    profile_schema = [
        bigquery.SchemaField("display_name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("gender", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("age", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("height_cm", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("weight_kg", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("max_hr", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("resting_hr", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    
    profile_table = bigquery.Table(profile_table_id, schema=profile_schema)
    client.create_table(profile_table, exists_ok=True)
    print(f"✅ Table {profile_table_id} ready.")

    # 2. Body Composition Table (Historical)
    body_table_id = f"{PROJECT_ID}.{DATASET_ID}.body_composition"
    body_schema = [
        bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("weight_kg", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("bmi", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("fat_percentage", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("muscle_mass_kg", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("water_percentage", "FLOAT64", mode="NULLABLE"),
    ]
    
    body_table = bigquery.Table(body_table_id, schema=body_schema)
    body_table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="date")
    
    client.create_table(body_table, exists_ok=True)
    print(f"✅ Table {body_table_id} ready.")

if __name__ == "__main__":
    create_profile_tables()
