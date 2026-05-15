"""Script to debug historical activities and their telemetry in BigQuery."""

import os
from typing import Any

from google.cloud import bigquery

from src.utils.config import setup_environment


def debug_historical_activities() -> None:
    """Checks metadata and telemetry for specific historical activity IDs."""
    setup_environment()
    client = bigquery.Client()
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    dataset = os.getenv("DATASET_NAME", "biometric_data_dev")

    ids = ["18916955905", "18935473640", "18935474486"]
    ids_str = ", ".join([f"'{i}'" for i in ids])

    print(f"--- Checking metadata for activities in {dataset} ---")
    query_meta = (
        f"SELECT id, date, name, type, distance_m, avg_hr "
        f"FROM `{project}.{dataset}.recent_activities` "
        f"WHERE CAST(id AS STRING) IN ({ids_str})"
    )
    rows_meta = list(client.query(query_meta).result())
    for r in rows_meta:
        row_dict: dict[str, Any] = dict(r)
        print(row_dict)

    print("\n--- Checking telemetry (ticks) for these IDs ---")
    query_tel = (
        f"SELECT activity_id, count(*) as tick_count "
        f"FROM `{project}.{dataset}.latest_activity_telemetry` "
        f"WHERE activity_id IN ({ids_str}) GROUP BY activity_id"
    )
    rows_tel = list(client.query(query_tel).result())
    for r in rows_tel:
        row_dict_tel: dict[str, Any] = dict(r)
        print(row_dict_tel)


def main() -> None:
    """Main entry point."""
    debug_historical_activities()


if __name__ == "__main__":
    main()
