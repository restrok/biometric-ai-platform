from google.cloud import bigquery
from src.utils.config import get_config, setup_environment

def migrate_schema():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    table_id = f"{config['project_id']}.{config['dataset_id']}.user_profile"
    
    table = client.get_table(table_id)
    existing_columns = [f.name for f in table.schema]
    
    new_fields = [
        bigquery.SchemaField("custom_z1_max", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("custom_z2_max", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("custom_z3_max", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("custom_z4_max", "INTEGER", mode="NULLABLE"),
    ]
    
    fields_to_add = [f for f in new_fields if f.name not in existing_columns]
    
    if fields_to_add:
        print(f"Adding columns: {[f.name for f in fields_to_add]}")
        table.schema += fields_to_add
        client.update_table(table, ["schema"])
        print("✅ Schema updated successfully.")
    else:
        print("✅ Schema already up to date.")

if __name__ == "__main__":
    migrate_schema()
