"""Script to debug activity date types and conversion."""

import datetime
import logging
import time
from typing import Any

from google.cloud import bigquery

from src.utils.config import get_config, setup_environment

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def debug_proactive_date() -> None:
    """Queries latest activity and prints date information."""
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = "biometric_data_dev"
    user_id = "fsirio"

    query_latest = f"""
        SELECT id, date, type, name 
        FROM `{config["project_id"]}.{dataset}.recent_activities`
        WHERE user_id = '{user_id}'
        ORDER BY date DESC
        LIMIT 1
    """
    results = list(client.query(query_latest).result())
    if not results:
        print("No activities found")
        return

    activity = results[0]
    print(f"ID: {activity.id}")
    print(f"Date: {activity.date}")
    print(f"Date Type: {type(activity.date)}")

    try:
        val: Any = activity.date
        if isinstance(val, (int, float)):
            print(f"localtime result: {time.localtime(val)}")
        elif isinstance(val, datetime.datetime):
            print(f"localtime on timestamp: {time.localtime(val.timestamp())}")
    except Exception as e:
        print(f"Error calling localtime: {e}")


def main() -> None:
    """Main entry point."""
    debug_proactive_date()


if __name__ == "__main__":
    main()
