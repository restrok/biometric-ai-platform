from google.cloud import bigquery

from src.utils.config import get_config, setup_environment


def check_schema():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config['project_id'])
    table_id = f"{config['project_id']}.{config['dataset_id']}.user_profile"
    table = client.get_table(table_id)
    print("Schema for user_profile:")
    for field in table.schema:
        print(f"{field.name}: {field.field_type}")

if __name__ == "__main__":
    check_schema()
