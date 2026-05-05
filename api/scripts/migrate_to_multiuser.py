import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DATASET_ID = os.getenv("DATASET_NAME", "biometric_data_dev")
DEFAULT_USER_ID = "fsirio"  # The user confirmed all existing data is theirs

TABLES = [
    "user_profile",
    "body_composition",
    "scheduled_workouts",
    "user_health_status",
    "recent_activities",
    "latest_activity_telemetry",
    "sleep_history",
    "hrv_history",
    "training_status"
]

def migrate():
    client = bigquery.Client(project=PROJECT_ID)
    
    for table_name in TABLES:
        table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
        print(f"⌛ Migrating table: {table_id}...")
        
        try:
            table = client.get_table(table_id)
            
            # 1. Check if user_id column exists
            has_user_id = any(field.name == "user_id" for field in table.schema)
            
            if not has_user_id:
                print(f"  Adding 'user_id' column to {table_name}...")
                new_schema = table.schema[:]
                new_schema.append(bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"))
                table.schema = new_schema
                client.update_table(table, ["schema"])
                print("  ✅ Column added.")
            else:
                print("  'user_id' column already exists.")

            # 2. Backfill existing rows with the default user ID
            print(f"  Backfilling existing rows with user_id='{DEFAULT_USER_ID}'...")
            update_query = f"""
                UPDATE `{table_id}`
                SET user_id = '{DEFAULT_USER_ID}'
                WHERE user_id IS NULL
            """
            query_job = client.query(update_query)
            query_job.result()
            print("  ✅ Backfill complete.")
            
        except Exception as e:
            print(f"  ❌ Error migrating {table_name}: {e}")

if __name__ == "__main__":
    if not PROJECT_ID:
        print("❌ Error: GOOGLE_CLOUD_PROJECT environment variable not set.")
    else:
        migrate()
