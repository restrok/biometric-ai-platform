"""Script to check the schema of the user_profile table in BigQuery."""

from google.cloud import bigquery

from src.utils.config import get_config, setup_environment


def check_schema() -> None:
    """Fetches and prints the schema for the user_profile table."""
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    table_id = f"{config['project_id']}.{config['dataset_id']}.user_profile"
    table = client.get_table(table_id)
    print("Schema for user_profile:")
    for field in table.schema:
        print(f"{field.name}: {field.field_type}")


def main() -> None:
    """Main entry point."""
    check_schema()


if __name__ == "__main__":
    main()
