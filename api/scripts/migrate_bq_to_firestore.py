import logging
import os
from datetime import datetime
from pathlib import Path

import google.cloud.firestore as firestore  # type: ignore[attr-defined]
from dotenv import load_dotenv
from google.cloud import bigquery

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
DATASET_ID = os.getenv("DATASET_ID", "biometric_data_dev")


def migrate():
    bq = bigquery.Client(project=PROJECT_ID)
    db = firestore.Client(project=PROJECT_ID)

    log.info(f"🚀 Starting migration from BQ ({DATASET_ID}) to Firestore (user_profiles)")

    # 1. Get all unique users
    query_users = f"SELECT DISTINCT user_id FROM `{PROJECT_ID}.{DATASET_ID}.user_profile` WHERE user_id IS NOT NULL"
    users = [row.user_id for row in bq.query(query_users).result()]

    log.info(f"Found {len(users)} users to migrate: {users}")

    for user_id in users:
        log.info(f"👤 Migrating data for user: {user_id}")
        profile_data = {}

        # --- A. Profile & Zones ---
        query_p = f"SELECT gender, age, height_cm, weight_kg, max_hr, resting_hr, custom_z1_max, custom_z2_max, custom_z3_max, custom_z4_max, display_name FROM `{PROJECT_ID}.{DATASET_ID}.user_profile` WHERE user_id = '{user_id}' LIMIT 1"
        p_rows = list(bq.query(query_p).result())
        if p_rows:
            p = dict(p_rows[0])
            # Basic fields
            for field in ["display_name", "gender", "age", "height_cm", "weight_kg", "max_hr", "resting_hr"]:
                if p.get(field) is not None:
                    profile_data[field] = p[field]

            # Zones
            profile_data["custom_zones"] = {
                "z1_max": p.get("custom_z1_max"),
                "z2_max": p.get("custom_z2_max"),
                "z3_max": p.get("custom_z3_max"),
                "z4_max": p.get("custom_z4_max"),
            }
            log.info("  ✅ Profile & Zones extracted")

        # --- B. Active Goals ---
        query_g = f"SELECT id, target_date, goal_type, target_value, description, status FROM `{PROJECT_ID}.{DATASET_ID}.user_goals` WHERE user_id = '{user_id}' AND status = 'active'"
        g_rows = [
            dict(row) for bq_row in bq.query(query_g).result() for row in [bq_row]
        ]  # list comprehension to avoid bq row issues
        if g_rows:
            profile_data["active_goals"] = []
            for g in g_rows:
                profile_data["active_goals"].append(
                    {
                        "id": g.get("id"),
                        "target_date": str(g.get("target_date")),
                        "goal_type": g.get("goal_type"),
                        "target_value": g.get("target_value"),
                        "description": g.get("description"),
                        "status": g.get("status"),
                    }
                )
            log.info(f"  ✅ {len(g_rows)} Active Goals extracted")

        # --- C. Latest Health Status ---
        query_h = f"SELECT date, feeling, notes, fatigue_level, injury_notes FROM `{PROJECT_ID}.{DATASET_ID}.user_health_status` WHERE user_id = '{user_id}' ORDER BY date DESC LIMIT 1"
        h_rows = list(bq.query(query_h).result())
        if h_rows:
            h = dict(h_rows[0])
            profile_data["latest_health_status"] = {
                "date": str(h.get("date")),
                "feeling": h.get("feeling"),
                "notes": h.get("notes"),
                "fatigue_level": h.get("fatigue_level"),
                "injury_notes": h.get("injury_notes"),
            }
            log.info(f"  ✅ Latest Health Status extracted ({h.get('date')})")

        # --- D. Calibration Markers (PCP) ---
        query_c = f"SELECT marker_type, marker_value, context, updated_at FROM `{PROJECT_ID}.{DATASET_ID}.user_calibration_profile` WHERE user_id = '{user_id}'"
        c_rows = [dict(row) for bq_row in bq.query(query_c).result() for row in [bq_row]]
        if c_rows:
            profile_data["personal_calibration_profile"] = {}
            for c in c_rows:
                m_type = c.get("marker_type")
                profile_data["personal_calibration_profile"][m_type] = {
                    "value": c.get("marker_value"),
                    "context": c.get("context"),
                    "updated_at": c["updated_at"].isoformat() if c.get("updated_at") else None,
                }
            log.info(f"  ✅ {len(c_rows)} Calibration Markers extracted")

        # --- E. Default Flags ---
        # Assume existing users have been synced at least once in the past
        profile_data["full_etl_synced"] = True
        profile_data["updated_at"] = datetime.utcnow().isoformat()

        # --- F. Write to Firestore ---
        doc_ref = db.collection("user_profiles").document(user_id)
        doc_ref.set(profile_data, merge=True)
        log.info(f"  🚀 Firestore document for {user_id} updated successfully.")

    log.info("✨ Migration completed.")


if __name__ == "__main__":
    migrate()
