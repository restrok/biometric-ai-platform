"""Migration script for sleep telemetry and alert dedup.

Applies schema updates to:
1. BigQuery (GCP storage): sleep_history, daily_physiology, hrv_history, hrv_readings_history, alert_dispatch_log
2. Local databases (SQLite + DuckDB):
   - SQLite: alert_dispatch_log
   - DuckDB: daily_physiology (body_battery_charged_sleep), hrv_readings_history
Includes automatic timestamped backups before applying local migrations.
"""

import argparse
import logging
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from dotenv import load_dotenv

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
DATASET_ID = "biometric_data_dev"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def migrate_bigquery_schemas() -> None:
    """Migrates BigQuery schemas for sleep telemetry and alert dispatch log."""
    from google.cloud import bigquery

    log.info(f"🚀 Starting BigQuery schema migration for project {PROJECT_ID}, dataset {DATASET_ID}...")
    try:
        client = bigquery.Client(project=PROJECT_ID)
    except Exception as e:
        log.warning(f"⚠️ Could not initialize BigQuery client ({e}). Skipping BigQuery migration.")
        return

    # 1. sleep_history: Add restless_moments
    sleep_table_id = f"{PROJECT_ID}.{DATASET_ID}.sleep_history"
    try:
        sleep_table = client.get_table(sleep_table_id)
        existing_cols = {f.name for f in sleep_table.schema}
        if "restless_moments" not in existing_cols:
            log.info(f"Adding restless_moments column to {sleep_table_id}")
            new_schema = list(sleep_table.schema) + [
                bigquery.SchemaField(
                    "restless_moments",
                    "INTEGER",
                    mode="NULLABLE",
                    description="Garmin restless moments count during sleep",
                )
            ]
            sleep_table.schema = new_schema
            client.update_table(sleep_table, ["schema"])
            log.info("✅ restless_moments column added to sleep_history.")
        else:
            log.info("ℹ️ restless_moments already exists in sleep_history.")
    except Exception as e:
        log.error(f"❌ Failed to update sleep_history schema: {e}")

    # 2. daily_physiology: Add body_battery_charged_sleep
    phys_table_id = f"{PROJECT_ID}.{DATASET_ID}.daily_physiology"
    try:
        phys_table = client.get_table(phys_table_id)
        existing_cols = {f.name for f in phys_table.schema}
        if "body_battery_charged_sleep" not in existing_cols:
            log.info(f"Adding body_battery_charged_sleep column to {phys_table_id}")
            new_schema = list(phys_table.schema) + [
                bigquery.SchemaField(
                    "body_battery_charged_sleep",
                    "INTEGER",
                    mode="NULLABLE",
                    description="Net body battery recharge during nocturnal sleep window (end_bb - start_bb)",
                )
            ]
            phys_table.schema = new_schema
            client.update_table(phys_table, ["schema"])
            log.info("✅ body_battery_charged_sleep column added to daily_physiology.")
        else:
            log.info("ℹ️ body_battery_charged_sleep already exists in daily_physiology.")
    except Exception as e:
        log.error(f"❌ Failed to update daily_physiology schema: {e}")

    # 3. hrv_history: Add hrv_first_half_avg, hrv_second_half_avg, hrv_decay_slope
    hrv_table_id = f"{PROJECT_ID}.{DATASET_ID}.hrv_history"
    try:
        hrv_table = client.get_table(hrv_table_id)
        existing_cols = {f.name for f in hrv_table.schema}
        hrv_new_fields = [
            bigquery.SchemaField(
                "hrv_first_half_avg",
                "FLOAT64",
                mode="NULLABLE",
                description="rMSSD average during 1st half of the night",
            ),
            bigquery.SchemaField(
                "hrv_second_half_avg",
                "FLOAT64",
                mode="NULLABLE",
                description="rMSSD average during 2nd half of the night",
            ),
            bigquery.SchemaField(
                "hrv_decay_slope",
                "FLOAT64",
                mode="NULLABLE",
                description="Linear regression slope across overnight 5-min readings series",
            ),
        ]
        to_add = [f for f in hrv_new_fields if f.name not in existing_cols]
        if to_add:
            log.info(f"Adding {[f.name for f in to_add]} to {hrv_table_id}")
            hrv_table.schema = list(hrv_table.schema) + to_add
            client.update_table(hrv_table, ["schema"])
            log.info("✅ Intra-sleep HRV columns added to hrv_history.")
        else:
            log.info("ℹ️ Intra-sleep HRV columns already exist in hrv_history.")
    except Exception as e:
        log.error(f"❌ Failed to update hrv_history schema: {e}")

    # 4. hrv_readings_history: Create table
    hrv_readings_table_id = f"{PROJECT_ID}.{DATASET_ID}.hrv_readings_history"
    readings_schema = [
        bigquery.SchemaField("date", "STRING", mode="REQUIRED", description="Calendar date (YYYY-MM-DD)"),
        bigquery.SchemaField(
            "timestamp_ms", "INT64", mode="REQUIRED", description="Reading epoch timestamp in milliseconds"
        ),
        bigquery.SchemaField("hrv_value", "FLOAT64", mode="REQUIRED", description="5-minute rMSSD HRV reading"),
        bigquery.SchemaField("user_id", "STRING", mode="REQUIRED", description="Internal user identifier"),
    ]
    readings_table = bigquery.Table(hrv_readings_table_id, schema=readings_schema)
    try:
        client.create_table(readings_table, exists_ok=True)
        log.info(f"✅ Table {hrv_readings_table_id} is ready.")
    except Exception as e:
        log.error(f"❌ Failed to create {hrv_readings_table_id}: {e}")

    # 5. alert_dispatch_log: Create table
    alert_log_table_id = f"{PROJECT_ID}.{DATASET_ID}.alert_dispatch_log"
    alert_schema = [
        bigquery.SchemaField(
            "alert_key", "STRING", mode="REQUIRED", description="sha256(alert_type|data_date|payload_hash)"
        ),
        bigquery.SchemaField(
            "alert_type", "STRING", mode="REQUIRED", description="Type of alert e.g. immune_radar, acwr_workload"
        ),
        bigquery.SchemaField(
            "data_date", "DATE", mode="REQUIRED", description="Date of the biometric data triggering the alert"
        ),
        bigquery.SchemaField(
            "payload_hash", "STRING", mode="REQUIRED", description="sha256 hash of triggering payload values"
        ),
        bigquery.SchemaField("sent_at", "TIMESTAMP", mode="REQUIRED", description="Timestamp of dispatch"),
        bigquery.SchemaField("channel", "STRING", mode="REQUIRED", description="Delivery channel e.g. telegram"),
        bigquery.SchemaField("user_id", "STRING", mode="REQUIRED", description="Internal user identifier"),
    ]
    alert_table = bigquery.Table(alert_log_table_id, schema=alert_schema)
    alert_table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="data_date"
    )
    try:
        client.create_table(alert_table, exists_ok=True)
        log.info(f"✅ Table {alert_log_table_id} is ready and partitioned by data_date.")
    except Exception as e:
        log.error(f"❌ Failed to create {alert_log_table_id}: {e}")

    log.info("🎉 BigQuery migration finished.")


def backup_database(file_path: Path, timestamp_str: str) -> Path | None:
    """Creates a timestamped backup of the database file if it exists."""
    if not file_path.exists():
        return None
    backup_path = file_path.parent / f"{file_path.name}.backup_{timestamp_str}"
    shutil.copy2(file_path, backup_path)
    log.info(f"📦 Backup created: {backup_path} ({backup_path.stat().st_size} bytes)")
    return backup_path


def migrate_local_sqlite(sqlite_path: Path) -> dict[str, int | str]:
    """Applies migrations to biometric.sqlite."""
    log.info(f"🛠️ Migrating SQLite database: {sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_dispatch_log (
                alert_key TEXT PRIMARY KEY,
                alert_type TEXT NOT NULL,
                data_date TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                channel TEXT NOT NULL,
                user_id TEXT NOT NULL
            );
        """)
        conn.commit()

        # Verification
        cursor.execute("PRAGMA table_info(alert_dispatch_log);")
        columns = [row[1] for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM alert_dispatch_log;")
        count = cursor.fetchone()[0]
        log.info(f"✅ SQLite alert_dispatch_log verified. Columns: {columns}, Rows: {count}")
        return {"table": "alert_dispatch_log", "columns": ", ".join(columns), "count": count}
    finally:
        conn.close()


def migrate_local_duckdb(duckdb_path: Path) -> dict[str, dict[str, int | str]]:
    """Applies migrations to biometric.duckdb."""
    log.info(f"🛠️ Migrating DuckDB database: {duckdb_path}")
    conn = duckdb.connect(str(duckdb_path))
    try:
        # 1. Add body_battery_charged_sleep to daily_physiology if table exists
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]

        phys_count = 0
        if "daily_physiology" in tables:
            conn.execute("ALTER TABLE daily_physiology ADD COLUMN IF NOT EXISTS body_battery_charged_sleep INTEGER;")
            row_p = conn.execute("SELECT COUNT(*) FROM daily_physiology").fetchone()
            phys_count = int(row_p[0]) if row_p is not None else 0
            log.info(f"✅ DuckDB daily_physiology column body_battery_charged_sleep added/verified. Rows: {phys_count}")

        # 2. Create hrv_readings_history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hrv_readings_history (
                date VARCHAR,
                timestamp_ms BIGINT,
                hrv_value DOUBLE,
                user_id VARCHAR,
                PRIMARY KEY (user_id, timestamp_ms)
            );
        """)
        row_h = conn.execute("SELECT COUNT(*) FROM hrv_readings_history").fetchone()
        hrv_count = int(row_h[0]) if row_h is not None else 0
        log.info(f"✅ DuckDB hrv_readings_history table verified. Rows: {hrv_count}")

        # Column verification
        cols_phys = (
            [c[0] for c in conn.execute("DESCRIBE daily_physiology").fetchall()] if "daily_physiology" in tables else []
        )
        cols_hrv = [c[0] for c in conn.execute("DESCRIBE hrv_readings_history").fetchall()]

        return {
            "daily_physiology": {"columns": ", ".join(cols_phys), "count": phys_count},
            "hrv_readings_history": {"columns": ", ".join(cols_hrv), "count": hrv_count},
        }
    finally:
        conn.close()


def migrate_data_dir(data_dir: Path) -> dict[str, object]:
    """Runs backup and migrations on a given data directory."""
    if not data_dir.exists():
        log.warning(f"Directory {data_dir} does not exist, skipping.")
        return {}

    sqlite_path = data_dir / "biometric.sqlite"
    duckdb_path = data_dir / "biometric.duckdb"

    if not sqlite_path.exists() and not duckdb_path.exists():
        log.info(f"No database files found in {data_dir}, skipping.")
        return {}

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    log.info(f"📁 Processing data directory: {data_dir} (Timestamp: {ts})")

    # 1. Backups
    sqlite_backup = backup_database(sqlite_path, ts)
    duckdb_backup = backup_database(duckdb_path, ts)

    results: dict[str, object] = {
        "data_dir": str(data_dir),
        "timestamp": ts,
        "sqlite_backup": str(sqlite_backup) if sqlite_backup else None,
        "duckdb_backup": str(duckdb_backup) if duckdb_backup else None,
    }

    # 2. Migrations & Verifications
    if sqlite_path.exists():
        results["sqlite"] = migrate_local_sqlite(sqlite_path)

    if duckdb_path.exists():
        results["duckdb"] = migrate_local_duckdb(duckdb_path)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate BigQuery and Local databases for sleep telemetry & alert dedup."
    )
    parser.add_argument("--local-only", action="store_true", help="Skip BigQuery schema migrations")
    parser.add_argument("--bq-only", action="store_true", help="Skip local database migrations")
    parser.add_argument("--data-dirs", nargs="*", help="Specific data directories to migrate")
    args = parser.parse_args()

    # 1. BigQuery Migration
    if not args.local_only:
        migrate_bigquery_schemas()

    # 2. Local DB Migrations
    if not args.bq_only:
        candidate_dirs = [
            Path("/home/fsirio/biometric-ai-platform/api/data"),
            Path("/home/fsirio/homelab/biometric-coach/data"),
            Path("/home/fsirio/homelab/biometric-coach-dev/data"),
        ]
        if args.data_dirs:
            candidate_dirs = [Path(d) for d in args.data_dirs]

        for d in candidate_dirs:
            if d.exists():
                res = migrate_data_dir(d)
                log.info(f"Migration summary for {d}: {res}")


if __name__ == "__main__":
    main()
