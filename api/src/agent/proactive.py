import logging
import time

from google.cloud import bigquery

from src.tools.analytics import analyze_activity_efficiency
from src.tools.retriever import retrieve_biometric_data
from src.utils.config import get_config
from src.utils.notifications import send_proactive_notification

log = logging.getLogger(__name__)


def run_proactive_analysis(user_id: str):
    """
    Analyzes the latest biometric data and sends proactive notifications
    if physiological anomalies are detected.
    """
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]

    log.info(f"🧠 Starting proactive analysis for user: {user_id}")

    # 1. Check for recent activities that haven't been notified
    # We need a way to track what we've already processed.
    # For now, let's look at the latest activity from the last 6 hours.

    query_latest = f"""
        SELECT id, date, type 
        FROM `{config["project_id"]}.{dataset}.recent_activities`
        WHERE user_id = '{user_id}'
        AND date >= UNIX_SECONDS(TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR))
        ORDER BY date DESC
        LIMIT 1
    """

    try:
        results = list(client.query(query_latest).result())
        if results:
            activity = results[0]
            activity_id = str(activity.id)

            # Check if notified already (using a simple local cache or a BQ table)
            if not _has_been_notified(client, dataset, user_id, activity_id, "hydration"):
                _analyze_hydration(user_id, activity_id)

            if not _has_been_notified(client, dataset, user_id, activity_id, "neuromuscular"):
                _analyze_neuromuscular_fatigue(user_id, activity_id)

            if not _has_been_notified(client, dataset, user_id, activity_id, "rpe_request"):
                _request_rpe(user_id, activity_id)

        # 2. Check HRV Status
        _analyze_hrv_status(user_id)

    except Exception as e:
        log.error(f"❌ Proactive analysis failed: {e}")


def _has_been_notified(client, dataset, user_id, entity_id, notification_type):
    """Checks if a notification has already been sent to avoid duplicates."""
    table_id = f"{client.project}.{dataset}.proactive_notifications_log"

    # Create table if not exists (lazy init)
    _ensure_log_table_exists(client, table_id)

    query = f"""
        SELECT COUNT(*) as count 
        FROM `{table_id}`
        WHERE user_id = '{user_id}' 
        AND entity_id = '{entity_id}'
        AND type = '{notification_type}'
    """
    results = list(client.query(query).result())
    return results[0].count > 0


def _ensure_log_table_exists(client, table_id):
    schema = [
        bigquery.SchemaField("user_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entity_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("sent_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("message", "STRING"),
    ]
    try:
        client.get_table(table_id)
    except Exception:
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table)
        log.info(f"Created proactive log table: {table_id}")


def _log_notification(user_id, entity_id, notification_type, message):
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]
    table_id = f"{config['project_id']}.{dataset}.proactive_notifications_log"

    rows_to_insert = [
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "type": notification_type,
            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "message": message,
        }
    ]
    client.insert_rows_json(table_id, rows_to_insert)


def _analyze_hydration(user_id, activity_id):
    log.info(f"💧 Analyzing hydration for activity {activity_id}...")
    efficiency = analyze_activity_efficiency.invoke({"activity_id": activity_id, "user_id": user_id})

    if isinstance(efficiency, dict) and "aerobic_decoupling_pct" in efficiency:
        drift_str = efficiency["aerobic_decoupling_pct"].replace("%", "")
        try:
            drift = float(drift_str)
            if drift > 5.0:
                # Calculate rehydration needs: Basic formula for 77kg user
                # 1.5L for 6% drift is roughly what we discussed.
                liters = round(drift * 0.25, 1)  # 6% -> 1.5L

                msg = (
                    f"🚨 *Silent Dehydration Detected*\n\n"
                    f"Your efficiency dropped by {drift}% during your run today. "
                    f"Your body is under cardiovascular stress even if you don't feel thirsty.\n\n"
                    f"👉 *Mandatory Protocol:* Drink at least {liters}L of electrolytes in the next 2 hours."
                )

                if send_proactive_notification(user_id, msg):
                    _log_notification(user_id, activity_id, "hydration", msg)
                    log.info(f"✅ Hydration alert sent for {activity_id}")
        except ValueError:
            pass


def _analyze_hrv_status(user_id):
    log.info(f"💤 Analyzing HRV status for user {user_id}...")
    data = retrieve_biometric_data.invoke({"user_id": user_id})
    hrv_history = data.get("hrv", [])

    if hrv_history:
        latest_hrv = hrv_history[0]
        status = latest_hrv.get("status")
        date = latest_hrv.get("date")

        if status in ["UNBALANCED", "LOW"]:
            # Check if notified for this date already
            config = get_config()
            client = bigquery.Client(project=config["project_id"])
            dataset = config["dataset_id"]

            if not _has_been_notified(client, dataset, user_id, date, "hrv_stress"):
                baseline = f"{latest_hrv.get('baseline_low')}-{latest_hrv.get('baseline_high')}ms"
                msg = (
                    f"⚠️ *Recovery Alert: HRV {status}*\n\n"
                    f"Your HRV today is {latest_hrv.get('avg_hrv')}ms, which is below your typical baseline of {baseline}.\n\n"
                    f"Your nervous system is under stress. Today should be a *Rest Day* or very light Z1 recovery."
                )
                if send_proactive_notification(user_id, msg):
                    _log_notification(user_id, date, "hrv_stress", msg)
                    log.info(f"✅ HRV stress alert sent for {date}")


def _analyze_neuromuscular_fatigue(user_id, activity_id):
    log.info(f"🦵 Analyzing neuromuscular fatigue for activity {activity_id}...")
    efficiency = analyze_activity_efficiency.invoke({"activity_id": activity_id, "user_id": user_id})

    if isinstance(efficiency, dict) and "gct_first_half" in efficiency and "gct_second_half" in efficiency:
        gct1 = efficiency["gct_first_half"]
        gct2 = efficiency["gct_second_half"]

        if gct1 and gct2 and gct1 > 0:
            gct_drift = ((gct2 - gct1) / gct1) * 100

            # Threshold: > 4% increase in GCT indicates significant form breakdown
            if gct_drift > 4.0:
                msg = (
                    f"🦵 *Form Breakdown Detected*\n\n"
                    f"Your Ground Contact Time (GCT) increased by {round(gct_drift, 1)}% in the second half of your run. "
                    f"This indicates neuromuscular fatigue and lost 'stiffness' in your stride.\n\n"
                    f"👉 *Advice:* Your next session should include 4-6 recovery strides (20s fast/relaxed) "
                    f"to reset your form and neuromuscular recruitment."
                )

                if send_proactive_notification(user_id, msg):
                    _log_notification(user_id, activity_id, "neuromuscular", msg)
                    log.info(f"✅ Neuromuscular fatigue alert sent for {activity_id}")


def _request_rpe(user_id, activity_id):
    log.info(f"🤔 Requesting RPE for activity {activity_id}...")
    msg = (
        "🏃 *Activity Synced: Tigre Running*\n\n"
        "Great job on your run! To calibrate your recovery model, "
        "how did you feel on a scale of 1-10? (1 = very easy, 10 = max effort)"
    )

    if send_proactive_notification(user_id, msg):
        _log_notification(user_id, activity_id, "rpe_request", msg)
        log.info(f"✅ RPE request sent for {activity_id}")
