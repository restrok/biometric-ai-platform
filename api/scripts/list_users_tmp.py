from google.cloud import bigquery

from src.utils.config import get_config, setup_environment


def list_users():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    table_id = f"{config['project_id']}.{config['dataset_id']}.user_profile"
    query = f"SELECT user_id, display_name FROM `{table_id}`"
    results = list(client.query(query).result())
    for row in results:
        print(f"ID: {row.user_id}, Name: {row.display_name}")


if __name__ == "__main__":
    list_users()
