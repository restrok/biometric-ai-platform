from google.cloud import bigquery

from src.utils.config import get_config, setup_environment


def check_profile():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config['project_id'])
    table_id = f"{config['project_id']}.{config['dataset_id']}.user_profile"
    query = f"SELECT * FROM `{table_id}`"
    results = list(client.query(query).result())
    print(f"Found {len(results)} rows in user_profile.")
    if results:
        print(dict(results[0]))

if __name__ == "__main__":
    check_profile()
