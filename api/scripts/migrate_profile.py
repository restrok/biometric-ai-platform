"""Script to migrate the user_profile table by adding missing columns."""

from google.cloud import bigquery

from src.utils.config import get_config, setup_environment


def migrate_profile_table() -> None:
    """Adds custom heart rate zone columns to the user_profile table."""
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
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


def main() -> None:
    """Main entry point."""
    migrate_profile_table()


if __name__ == "__main__":
    main()
