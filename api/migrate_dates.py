import logging

from google.cloud import bigquery

from src.utils.config import get_config, setup_environment

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def migrate_historical_dates():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = "biometric_data_dev"

    # 1. Fix recent_activities (INTEGER date)
    log.info("Cleaning up recent_activities...")
    q1 = f"""
        UPDATE `{config["project_id"]}.{dataset}.recent_activities`
        SET date = CAST(date / 1000000000 AS INT64)
        WHERE date > 1000000000000000
    """
    try:
        job = client.query(q1)
        job.result()
        log.info(f"✅ recent_activities updated: {job.num_dml_affected_rows} rows")
    except Exception as e:
        log.error(f"❌ recent_activities failed: {e}")

    # 2. Fix sleep_history and hrv_history (STRING dates like '2026-05-13')
    # These are safe because they are strings and don't contain nanosecond integers.
    log.info("Verifying sleep_history and hrv_history (STRING format)...")
    for table in ["sleep_history", "hrv_history"]:
        q = f"SELECT date FROM `{config['project_id']}.{dataset}.{table}` LIMIT 1"
        res = list(client.query(q).result())
        if res:
            log.info(f"✅ {table} looks good (Date example: {res[0].date})")


if __name__ == "__main__":
    migrate_historical_dates()
