import os
import base64
import pandas as pd
from google.cloud import bigquery
from pathlib import Path
from dotenv import load_dotenv

# Load and decode tokens
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)
api_key_raw = os.getenv("GOOGLE_API_KEY")

from garmin_training_toolkit_sdk.extractors import get_activity_telemetry
from garmin_training_toolkit_sdk.utils import get_authenticated_client, find_token_file

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DATASET_ID = "biometric_data_dev"
TABLE_ID = "latest_activity_telemetry"

def backfill_telemetry():
    print("🔄 Backfilling advanced metrics for last activities...")
    client = bigquery.Client(project=PROJECT_ID)
    
    # 1. Find the last 3 activity IDs
    query = f"SELECT DISTINCT activity_id FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` LIMIT 3"
    ids = [row.activity_id for row in client.query(query).result()]
    
    if not ids:
        print("❌ No activities found in BigQuery.")
        return

    # 2. Get Garmin Client
    token_file = find_token_file()
    garmin_client = get_authenticated_client(token_file)

    # 3. Fetch and Overwrite
    for act_id in ids:
        print(f"📥 Fetching advanced metrics for {act_id}...")
        telemetry = get_activity_telemetry(garmin_client, int(act_id))
        
        if telemetry and telemetry.ticks:
            df = pd.DataFrame([t.model_dump() for t in telemetry.ticks])
            df['activity_id'] = str(act_id)
            
            # We overwrite the telemetry for this specific ID
            # (In a PoC, we'll just append and you can filter, or use a DELETE + INSERT)
            print(f"💾 Saving {len(df)} ticks with advanced metrics...")
            
            # Delete old data for this ID to avoid duplicates
            client.query(f"DELETE FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` WHERE activity_id = '{act_id}'").result()
            
            # Load new data
            table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
            job = client.load_table_from_dataframe(df, table_ref)
            job.result()
            print(f"✅ Activity {act_id} updated.")

if __name__ == "__main__":
    backfill_telemetry()
