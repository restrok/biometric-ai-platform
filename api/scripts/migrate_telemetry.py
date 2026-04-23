import os
from google.cloud import bigquery
from pathlib import Path
from dotenv import load_dotenv

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
DATASET_ID = "biometric_data_dev"
TABLE_ID = "latest_activity_telemetry"

def migrate_telemetry_schema():
    print(f"🚀 Migrating schema for {TABLE_ID}...")
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = client.dataset(DATASET_ID).table(TABLE_ID)
    table = client.get_table(table_ref)
    
    new_fields = [
        bigquery.SchemaField("stride_length_mm", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("vertical_oscillation_cm", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("ground_contact_time_ms", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("temperature_c", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("run_walk_index", "FLOAT64", mode="NULLABLE"),
    ]
    
    # Only add fields that don't exist
    existing_field_names = {f.name for f in table.schema}
    fields_to_add = [f for f in new_fields if f.name not in existing_field_names]
    
    if fields_to_add:
        print(f"Adding columns: {[f.name for f in fields_to_add]}")
        new_schema = list(table.schema) + fields_to_add
        table.schema = new_schema
        client.update_table(table, ["schema"])
        print("✅ Schema updated successfully!")
    else:
        print("✅ All columns already exist. No migration needed.")

if __name__ == "__main__":
    migrate_telemetry_schema()
