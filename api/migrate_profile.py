from src.utils.config import get_config, setup_environment
from google.cloud import bigquery

def migrate_profile_table():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config['project_id'])
    table_id = f"{config['project_id']}.{config['dataset_id']}.user_profile"
    
    print(f"Migrating table: {table_id}")
    
    # Add missing columns
    queries = [
        f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS custom_z1_max INTEGER",
        f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS custom_z2_max INTEGER",
        f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS custom_z3_max INTEGER",
        f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS custom_z4_max INTEGER",
    ]
    
    for query in queries:
        try:
            client.query(query).result()
            print(f"Executed: {query}")
        except Exception as e:
            print(f"Failed to execute {query}: {e}")

if __name__ == "__main__":
    migrate_profile_table()
