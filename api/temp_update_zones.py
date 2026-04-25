from google.cloud import bigquery

from src.utils.config import get_config, setup_environment

setup_environment()

config = get_config()
project_id = config.get("project_id")
dataset = config.get("dataset_id")

if not project_id:
    print("Error: GOOGLE_CLOUD_PROJECT environment variable not set.")
    exit(1)

client = bigquery.Client(project=project_id)

table_id = f"{project_id}.{dataset}.user_profile"

z1_max = 143
z2_max = 165
z3_max = 176
z4_max = 186

sql_query = f"""
    UPDATE `{table_id}`
    SET
        custom_z1_max = {z1_max},
        custom_z2_max = {z2_max},
        custom_z3_max = {z3_max},
        custom_z4_max = {z4_max},
        updated_at = CURRENT_TIMESTAMP()
    WHERE TRUE
"""

try:
    query_job = client.query(sql_query)
    query_job.result()
    print(f"Successfully updated custom zones in BigQuery: Z1:{z1_max}, Z2:{z2_max}, Z3:{z3_max}, Z4:{z4_max}")
except Exception as e:
    print(f"Error updating custom zones: {e}")
