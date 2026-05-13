import logging
import time

from google.cloud import bigquery

from src.tools.analytics import analyze_activity_efficiency
from src.tools.retriever import retrieve_biometric_data
from src.utils.config import get_config
from src.utils.notifications import send_proactive_notification

log = logging.getLogger(__name__)


def run_proactive_analysis(user_id: str, new_activity_ids: list[str] | None = None):
    """
    Analyzed recent data. If new_activity_ids is provided, it only analyzes those.
    Then, it triggers an autonomous planning agent to schedule tomorrow.
    """
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]

    log.info(f"🧠 Starting proactive analysis and autonomous planning for user: {user_id}")

    # 1. Physical Analysis (Telemetry-based)
    activities_to_process = []
    if new_activity_ids:
        query_specific = f"""
            SELECT id, date, type, name 
            FROM `{config["project_id"]}.{dataset}.recent_activities`
            WHERE user_id = '{user_id}'
            AND id IN UNNEST({new_activity_ids})
        """
        activities_to_process = list(client.query(query_specific).result())
    else:
        query_latest = f"""
            SELECT id, date, type, name 
            FROM `{config["project_id"]}.{dataset}.recent_activities`
            WHERE user_id = '{user_id}'
            AND date >= UNIX_SECONDS(TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR))
            ORDER BY date DESC
            LIMIT 1
        """
        activities_to_process = list(client.query(query_latest).result())

    try:
        for activity in activities_to_process:
            activity_id = str(activity.id)
            activity_name = activity.name
            activity_date = activity.date

            if not _has_been_notified(client, dataset, user_id, activity_id, "hydration"):
                _analyze_hydration(user_id, activity_id, activity_name, activity_date)

            if not _has_been_notified(client, dataset, user_id, activity_id, "neuromuscular"):
                _analyze_neuromuscular_fatigue(user_id, activity_id, activity_name, activity_date)

            if not _has_been_notified(client, dataset, user_id, activity_id, "metabolic"):
                _analyze_metabolic_cost(user_id, activity_id, activity_name, activity_date)

        # 2. Health & Recovery Analysis
        _analyze_hrv_status(user_id)
        _check_health_pre_symptoms(user_id)

        # 3. Autonomous Planning for Tomorrow
        # We invoke the LangGraph agent with a specific "Planning Instruction"
        # This will trigger clear_calendar, prune_workouts, and upload_training_plan
        from langchain_core.messages import HumanMessage

        from src.agent.graph import graph
        
        planning_prompt = (
            "SYSTEM INSTRUCTION: It is 11:00 PM. Analyze my data from today and my current recovery state. "
            "1. Clear my calendar for tomorrow. "
            "2. Prune my workout library. "
            "3. Schedule the optimal session (or Rest Day) for tomorrow on my watch. "
            "Explain your reasoning based on today's telemetry and my health status."
        )
        
        log.info(f"📅 Triggering autonomous planner for {user_id}...")
        graph.invoke({
            "messages": [HumanMessage(content=planning_prompt)],
            "user_id": user_id,
            "loop_count": 0
        })

    except Exception as e:
        log.error(f"❌ Proactive analysis/planning failed: {e}")


def _analyze_metabolic_cost(user_id, activity_id, activity_name, activity_timestamp):
    log.info(f"🔥 Analyzing metabolic cost for activity {activity_id}...")
    efficiency = analyze_activity_efficiency.invoke({"activity_id": activity_id, "user_id": user_id})

    if isinstance(efficiency, dict) and "hr_per_step" in efficiency:
        hr_step = efficiency["hr_per_step"]
        # Threshold: > 0.95 HR/Step often indicates metabolic inefficiency for most runners
        if hr_step > 0.95:
            date_str = time.strftime("%A, %d %b", time.localtime(activity_timestamp))
            msg = (
                f"🔥 *Metabolic Efficiency Alert*\n\n"
                f"During your run '{activity_name}' on {date_str}, your Metabolic Cost was high ({hr_step} HR/Step).\n\n"
                f"💡 *Nutrition Advice for Tomorrow:* You burned more glycogen than usual today. "
                f"Prioritize complex carbohydrates in your breakfast tomorrow (oats, whole grains) to "
                f"fully restock your energy stores."
            )
            if send_proactive_notification(user_id, msg):
                _log_notification(user_id, activity_id, "metabolic", msg)


def _check_health_pre_symptoms(user_id):
    log.info(f"🩺 Checking for pre-symptom health markers for {user_id}...")
    try:
        data = retrieve_biometric_data.invoke({"user_id": user_id})
        hrv_history = data.get("hrv", [])
        
        if len(hrv_history) >= 2:
            latest = hrv_history[0]
            prev = hrv_history[1]
            
            hrv_drop = prev.get("avg_hrv", 0) - latest.get("avg_hrv", 0)
            # Placeholder for RHR check - in a real scenario we would fetch RHR specifically
            # For now, we use HRV trend which is a strong proxy.
            if hrv_drop > 15: # Significant drop
                msg = (
                    f"🩺 *Early Warning: Immune System Stress*\n\n"
                    f"Your HRV dropped significantly ({hrv_drop}ms) compared to yesterday.\n\n"
                    f"📅 *Plan for Tomorrow:* This often precedes a cold or overtraining. "
                    f"I have adjusted your plan to prioritize rest. Focus on hydration and extra sleep tonight."
                )
                if send_proactive_notification(user_id, msg):
                    _log_notification(user_id, "health", "pre_symptom", msg)
    except Exception as e:
        log.error(f"❌ Health pre-symptom check failed: {e}")


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


def _analyze_hydration(user_id, activity_id, activity_name, activity_timestamp):
    log.info(f"💧 Analyzing hydration for activity {activity_id}...")
    efficiency = analyze_activity_efficiency.invoke({"activity_id": activity_id, "user_id": user_id})

    if isinstance(efficiency, dict) and "aerobic_decoupling_pct" in efficiency:
        drift_str = efficiency["aerobic_decoupling_pct"].replace("%", "")
        try:
            drift = float(drift_str)
            if drift > 5.0:
                # Calculate rehydration needs: Conservative formula
                # We cap it at 1.5L to avoid hyponatremia risk.
                # Formula: 0.5L base + 0.1L per % above 5%, max 1.5L
                liters = min(1.5, round(0.5 + (drift - 5.0) * 0.1, 1))

                date_str = time.strftime("%A, %d %b", time.localtime(activity_timestamp))
                msg = (
                    f"🚨 *Cardiovascular Drift Detected*\n\n"
                    f"During your run '{activity_name}' on {date_str}, your efficiency dropped by {drift}%.\n\n"
                    f"💡 *Preparation for Tomorrow:* Your body is slightly more dehydrated than usual. "
                    f"In addition to what you drink tonight, make sure to start *tomorrow* with an extra {liters}L of electrolytes to "
                    f"fully restore your plasma volume and be ready for your next session."
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
                    f"⚠️ *Recovery Alert: HRV is {status}*\n\n"
                    f"Based on your latest data ({latest_hrv.get('avg_hrv')}ms), your nervous system is under stress (Baseline: {baseline}).\n\n"
                    f"📅 *Advice for Tomorrow:* Treat tomorrow as a *Rest Day* or keep it very light (Zone 1). "
                    f"Prioritize sleep and recovery tonight to bounce back."
                )
                if send_proactive_notification(user_id, msg):
                    _log_notification(user_id, date, "hrv_stress", msg)
                    log.info(f"✅ HRV stress alert sent for {date}")


def _analyze_neuromuscular_fatigue(user_id, activity_id, activity_name, activity_timestamp):
    log.info(f"🦵 Analyzing neuromuscular fatigue for activity {activity_id}...")
    efficiency = analyze_activity_efficiency.invoke({"activity_id": activity_id, "user_id": user_id})

    if isinstance(efficiency, dict) and "gct_first_half" in efficiency and "gct_second_half" in efficiency:
        gct1 = efficiency["gct_first_half"]
        gct2 = efficiency["gct_second_half"]

        if gct1 and gct2 and gct1 > 0:
            gct_drift = ((gct2 - gct1) / gct1) * 100

            # Threshold: > 4% increase in GCT indicates significant form breakdown
            if gct_drift > 4.0:
                date_str = time.strftime("%A, %d %b", time.localtime(activity_timestamp))
                msg = (
                    f"🦵 *Neuromuscular Fatigue Detected*\n\n"
                    f"In your run '{activity_name}' on {date_str}, your form showed breakdown (GCT increased by {round(gct_drift, 1)}%).\n\n"
                    f"👉 *Action Plan for Tomorrow:* Your nervous system needs a 'reset'. "
                    f"If you have a session tomorrow, include 4-6 recovery strides (20s fast/relaxed) at the end "
                    f"to improve neuromuscular recruitment and 'stiffness'."
                )

                if send_proactive_notification(user_id, msg):
                    _log_notification(user_id, activity_id, "neuromuscular", msg)
                    log.info(f"✅ Neuromuscular fatigue alert sent for {activity_id}")


def _request_rpe(user_id, activity_id, activity_name):
    log.info(f"🤔 Requesting RPE for activity {activity_id}...")
    msg = (
        f"🏃 *Activity Synced: {activity_name}*\n\n"
        "Great job on your run! To calibrate your recovery model, "
        "how did you feel on a scale of 1-10? (1 = very easy, 10 = max effort)"
    )

    if send_proactive_notification(user_id, msg):
        _log_notification(user_id, activity_id, "rpe_request", msg)
        log.info(f"✅ RPE request sent for {activity_id}")
