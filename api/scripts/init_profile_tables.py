import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DATASET_ID = "biometric_data_dev"


def create_profile_tables():
    client = bigquery.Client(project=PROJECT_ID)

    # 1. User Profile Table
    profile_table_id = f"{PROJECT_ID}.{DATASET_ID}.user_profile"
    profile_schema = [
        bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("display_name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("gender", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("age", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("height_cm", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("weight_kg", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("max_hr", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("resting_hr", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("custom_z1_max", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("custom_z2_max", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("custom_z3_max", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("custom_z4_max", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    profile_table = bigquery.Table(profile_table_id, schema=profile_schema)
    client.create_table(profile_table, exists_ok=True)
    print(f"✅ Table {profile_table_id} ready.")

    # 2. Body Composition Table (Historical)
    body_table_id = f"{PROJECT_ID}.{DATASET_ID}.body_composition"
    body_schema = [
        bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("weight_kg", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("bmi", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("fat_percentage", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("muscle_mass_kg", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("water_percentage", "FLOAT64", mode="NULLABLE"),
    ]

    body_table = bigquery.Table(body_table_id, schema=body_schema)
    body_table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="date")

    client.create_table(body_table, exists_ok=True)
    print(f"✅ Table {body_table_id} ready.")

    # 3. Scheduled Workouts Table
    scheduled_table_id = f"{PROJECT_ID}.{DATASET_ID}.scheduled_workouts"
    scheduled_schema = [
        bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("id", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("workout_id", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("title", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("sport_type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("description", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("duration_sec", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("distance_m", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    scheduled_table = bigquery.Table(scheduled_table_id, schema=scheduled_schema)
    scheduled_table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="date")

    client.create_table(scheduled_table, exists_ok=True)
    print(f"✅ Table {scheduled_table_id} ready.")

    # 4. User Health Status Table (Subjective & Health Tracking)
    health_table_id = f"{PROJECT_ID}.{DATASET_ID}.user_health_status"
    health_schema = [
        bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("feeling", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("notes", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("fatigue_level", "INTEGER", mode="NULLABLE"),  # 1-10 scale
        bigquery.SchemaField("injury_notes", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    health_table = bigquery.Table(health_table_id, schema=health_schema)
    health_table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="date")

    client.create_table(health_table, exists_ok=True)
    print(f"✅ Table {health_table_id} ready.")

    # 5. User Goals Table (Race targets, time objectives, etc.)
    goals_table_id = f"{PROJECT_ID}.{DATASET_ID}.user_goals"
    goals_schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("target_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("goal_type", "STRING", mode="REQUIRED"),  # 'race', 'volume', 'weight', etc.
        bigquery.SchemaField("target_value", "STRING", mode="REQUIRED"),  # '50:00', '100km', etc.
        bigquery.SchemaField("description", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("status", "STRING", mode="REQUIRED"),  # 'active', 'completed', 'abandoned'
        bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
    ]

    goals_table = bigquery.Table(goals_table_id, schema=goals_schema)
    client.create_table(goals_table, exists_ok=True)
    print(f"✅ Table {goals_table_id} ready.")

    # 6. Daily Physiology Table (24/7 Metrics)
    daily_table_id = f"{PROJECT_ID}.{DATASET_ID}.daily_physiology"
    daily_schema = [
        bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("resting_heart_rate", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("max_heart_rate", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("all_day_stress_avg", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("body_battery_end_of_day", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("total_steps", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    daily_table = bigquery.Table(daily_table_id, schema=daily_schema)
    daily_table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="date")

    client.create_table(daily_table, exists_ok=True)
    print(f"✅ Table {daily_table_id} ready.")

    # 7. User Calibration Profile (PCP Markers)
    calib_table_id = f"{PROJECT_ID}.{DATASET_ID}.user_calibration_profile"
    calib_schema = [
        bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("marker_type", "STRING", mode="REQUIRED"),  # 'ac_ratio_red_line', 'adaptation_peak', etc.
        bigquery.SchemaField("marker_value", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("context", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    calib_table = bigquery.Table(calib_table_id, schema=calib_schema)
    client.create_table(calib_table, exists_ok=True)
    print(f"✅ Table {calib_table_id} ready.")


if __name__ == "__main__":
    create_profile_tables()
