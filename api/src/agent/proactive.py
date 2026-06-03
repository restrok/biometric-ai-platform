import logging
import statistics
import time

from google.cloud import bigquery

from src.tools.analytics import analyze_activity_efficiency
from src.tools.retriever import retrieve_biometric_data
from src.utils.config import get_config
from src.utils.firestore import get_user_profile, update_user_profile
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

    # --- 0. Onboarding Check (Asynchronous ETL) ---
    profile = get_user_profile(user_id)
    if not profile.get("full_etl_synced"):
        log.info(f"🆕 User {user_id} is new or has no full sync. Triggering background historical ETL...")
        _trigger_async_historical_backfill(user_id)
        # Exit gracefully to avoid analyzing incomplete data
        return

    # 1. Physical Analysis (Telemetry-based)
    activities_to_process = []
    if new_activity_ids:
        # We use strings for ID comparison to be robust against BQ type inference quirks
        # which sometimes cause INT64 vs ARRAY<STRING> mismatches in the client library.
        str_ids = [str(aid) for aid in new_activity_ids if str(aid).strip()]

        if not str_ids:
            log.warning(f"No valid activity IDs found in {new_activity_ids}")
            return

        query_specific = f"""
            SELECT id, date, type, name 
            FROM `{config["project_id"]}.{dataset}.recent_activities`
            WHERE user_id = @user_id
            AND CAST(id AS STRING) IN UNNEST(@activity_ids)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ArrayQueryParameter("activity_ids", "STRING", str_ids),
            ]
        )
        activities_to_process = list(client.query(query_specific, job_config=job_config).result())
    else:
        query_latest = f"""
            SELECT id, date, type, name 
            FROM `{config["project_id"]}.{dataset}.recent_activities`
            WHERE user_id = @user_id
            AND date >= UNIX_SECONDS(TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR))
            ORDER BY date DESC
            LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            ]
        )
        activities_to_process = list(client.query(query_latest, job_config=job_config).result())

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

        # 3. Discovery Phase (Data Science)
        # Periodic 'rare' pattern discovery
        _run_discovery_phase(user_id)

        # 4. Autonomous Planning for Tomorrow
        # We invoke the LangGraph agent with a specific "Planning Instruction"
        # This will trigger clear_calendar, prune_workouts, and upload_training_plan
        from typing import cast

        from langchain_core.messages import HumanMessage
        from langchain_core.runnables import RunnableConfig

        from src.agent.graph import AgentState, graph

        planning_prompt = (
            "SYSTEM INSTRUCTION: It is late evening. Analyze the user's data from today and their current recovery state. "
            "1. Check `scheduled_workouts` for tomorrow. "
            "2. If a workout is ALREADY scheduled: "
            "   - Compare its intensity with the user's current HRV/Sleep status. "
            "   - If they are compatible, DO NOTHING. "
            "   - If the biometrics suggest the session is TOO RISKY (e.g., high-intensity planned but HRV is very low): "
            "     DO NOT clear, replace, or modify the calendar. "
            "     Instead, SEND A PROACTIVE NOTIFICATION explaining the physiological risk, "
            "     recommending an alternative, and ASKING for permission to make the change. "
            "3. If the calendar is EMPTY for tomorrow: "
            "   - DO NOT schedule anything autonomously. "
            "   - Instead, analyze the biometrics and recovery state, and SEND A PROACTIVE NOTIFICATION with a recommendation "
            "     (e.g., 'Your recovery is optimal. I recommend an Interval session today. Should I schedule it for you?'). "
            "4. IMPORTANT: NEVER schedule, replace, or clear workouts autonomously without explicit user confirmation via chat. "
            "   Your role is to advise and wait for approval. "
            "5. Explain your reasoning based on today's telemetry, health status, and existing plans."
        )

        log.info(f"📅 Triggering autonomous planner for {user_id}...")
        initial_state = cast(
            AgentState,
            {
                "messages": [HumanMessage(content=planning_prompt)],
                "user_id": user_id,
                "loop_count": 0,
                "biometric_context": {},
                "usage_stats": {"total_tokens": 0, "calls": 0, "total_cost_usd": 0.0},
                "intent": "full",
            },
        )
        # Use user_id as thread_id for continuity
        config = cast(RunnableConfig, {"configurable": {"thread_id": user_id}})
        graph.invoke(initial_state, config=config)

    except Exception as e:
        log.error(f"❌ Proactive analysis/planning failed: {e}")


def _run_discovery_phase(user_id: str):
    """
    Tasks the DataScientist node with finding non-obvious patterns or anomalies
    in the user's long-term data (30-90 days).
    """
    log.info(f"🧪 Activating Discovery Phase (Data Science) for {user_id}...")
    try:
        from typing import cast

        from langchain_core.messages import HumanMessage
        from langchain_core.runnables import RunnableConfig

        from src.agent.graph import AgentState, graph

        discovery_prompt = (
            "ROLE: Data Scientist. "
            "TASK: Perform an autonomous 'Discovery Audit' on the user's data from the last 30-90 days. "
            "1. **Audit Continuity:** Check `user_calibration_profile` for existing patterns. "
            "2. **Identify Interventions:** Analyze `semantic_memories` to identify recent lifestyle changes, supplementation (like Centrum), or injuries that could act as variables in your analysis. "
            "3. **Hypothesis & Exploration:** Formulate a hypothesis based on these interventions (e.g., 'Does the Magnesium in Centrum correlate with higher sleep HRV?') and execute exploratory SQL queries to validate them. "
            "4. **Persistence:** Use `save_calibration_marker` to update findings or create new ones. "
            "5. **Notification:** If a significant correlation or shift is found, SEND A PROACTIVE NOTIFICATION explaining the discovery. "
            "Total freedom to explore. Be the brain that finds the 'Why' behind the 'What'."
        )

        initial_state = cast(
            AgentState,
            {
                "messages": [HumanMessage(content=discovery_prompt)],
                "user_id": user_id,
                "loop_count": 0,
                "biometric_context": {},
                "usage_stats": {"total_tokens": 0, "calls": 0, "total_cost_usd": 0.0},
                "intent": "full",
            },
        )
        # The graph will now route this to the DataScientist node because of the exploratory tool calls
        config = cast(RunnableConfig, {"configurable": {"thread_id": user_id}})
        graph.invoke(initial_state, config=config)

    except Exception as e:
        log.error(f"❌ Discovery Phase failed: {e}")


def _safe_localtime(ts):
    """Handles timestamps in seconds, milliseconds, microseconds, or nanoseconds."""
    if not isinstance(ts, (int, float)):
        return time.localtime()

    # Heuristic to detect precision
    if ts > 1e18:  # Nanoseconds
        ts /= 1e9
    elif ts > 1e15:  # Microseconds
        ts /= 1e6
    elif ts > 1e12:  # Milliseconds
        ts /= 1e3

    try:
        return time.localtime(ts)
    except (OverflowError, OSError):
        # Fallback to current time if still failing
        return time.localtime()


def _analyze_metabolic_cost(user_id, activity_id, activity_name, activity_timestamp):
    log.info(f"🔥 Analyzing metabolic cost for activity {activity_id}...")
    efficiency = analyze_activity_efficiency.invoke({"activity_id": activity_id, "user_id": user_id})

    if isinstance(efficiency, dict) and "hr_per_step" in efficiency:
        hr_step = efficiency["hr_per_step"]
        # Threshold: > 0.95 HR/Step often indicates metabolic inefficiency for most runners
        if hr_step > 0.95:
            date_str = time.strftime("%A, %d %b", _safe_localtime(activity_timestamp))
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
    """
    Immune Radar: Statistical anomaly detection using Z-scores for HRV and RHR.
    Detects systemic stress that often precedes illness.
    """
    log.info(f"🩺 Checking for pre-symptom health markers for {user_id} (Z-Score analysis)...")
    try:
        data = retrieve_biometric_data.invoke({"user_id": user_id})

        # 1. HRV Z-Score (Last 7-21 days)
        hrv_history = data.get("hrv", [])
        if len(hrv_history) >= 7:
            hrv_values = [h.get("avg_hrv") for h in hrv_history if h.get("avg_hrv") is not None]
            if len(hrv_values) >= 5:
                today_hrv = hrv_values[0]
                mean_hrv = statistics.mean(hrv_values[1:])
                std_hrv = statistics.stdev(hrv_values[1:])

                hrv_z = (today_hrv - mean_hrv) / std_hrv if std_hrv > 0 else 0

                # 2. RHR Z-Score
                physiology = data.get("daily_physiology_7d", [])
                rhr_values = [
                    p.get("resting_heart_rate") for p in physiology if p.get("resting_heart_rate") is not None
                ]

                if len(rhr_values) >= 5:
                    today_rhr = rhr_values[0]
                    mean_rhr = statistics.mean(rhr_values[1:])
                    std_rhr = statistics.stdev(rhr_values[1:])

                rhr_z = (today_rhr - mean_rhr) / std_rhr if std_rhr > 0 else 0

                log.info(f"📊 Z-Scores for {user_id}: HRV Z={hrv_z:.2f}, RHR Z={rhr_z:.2f}")

                # Thresholds: HRV significantly LOW (Z < -1.5) AND RHR significantly HIGH (Z > 1.5)
                if hrv_z < -1.5 and rhr_z > 1.5:
                    msg = (
                        f"🩺 *Immune Radar Alert: Critical Deviation*\n\n"
                        f"My statistical analysis detected a significant anomaly in your recovery metrics today:\n"
                        f"• HRV is **{abs(hrv_z):.1f}σ below** your recent average.\n"
                        f"• RHR is **{rhr_z:.1f}σ above** your recent average.\n\n"
                        f"⚠️ *Warning:* This combination strongly suggests impending illness (cold/flu) or extreme systemic fatigue. "
                        f"I strongly recommend **cancelling any high-intensity training** tomorrow and prioritizing 8+ hours of sleep."
                    )
                    if send_proactive_notification(user_id, msg):
                        _log_notification(user_id, "health", "immune_radar", msg)
                elif hrv_z < -1.2:
                    # Mild warning
                    msg = (
                        f"🩺 *Health Warning: Low Readiness*\n\n"
                        f"Your HRV is trending significantly lower than your baseline (Z={hrv_z:.2f}). "
                        f"Listen to your body tomorrow; if you feel sluggish, consider a Zone 1 recovery run instead of your planned session."
                    )
                    if not _has_been_notified(
                        bigquery.Client(project=get_config()["project_id"]),
                        get_config()["dataset_id"],
                        user_id,
                        hrv_history[0].get("date"),
                        "hrv_warning",
                    ):
                        if send_proactive_notification(user_id, msg):
                            _log_notification(user_id, hrv_history[0].get("date"), "hrv_warning", msg)
    except Exception as e:
        log.error(f"❌ Immune Radar analysis failed: {e}")


def _has_been_notified(client, dataset, user_id, entity_id, notification_type):
    """Checks if a notification has already been sent to avoid duplicates."""
    table_id = f"{client.project}.{dataset}.proactive_notifications_log"

    # Create table if not exists (lazy init)
    _ensure_log_table_exists(client, table_id)

    query = f"""
        SELECT COUNT(*) as count 
        FROM `{table_id}`
        WHERE user_id = @user_id 
        AND entity_id = @entity_id
        AND type = @type
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("entity_id", "STRING", str(entity_id)),
            bigquery.ScalarQueryParameter("type", "STRING", notification_type),
        ]
    )
    results = list(client.query(query, job_config=job_config).result())
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

                date_str = time.strftime("%A, %d %b", _safe_localtime(activity_timestamp))
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
                date_str = time.strftime("%A, %d %b", _safe_localtime(activity_timestamp))
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


def _trigger_async_historical_backfill(user_id: str):
    """Spawns a background thread to perform the 90-day historical sync."""
    import threading

    from src.tools.etl_job import run_etl

    def backfill_task():
        try:
            log.info(f"⏳ Background ETL: Starting 90-day backfill for {user_id}...")
            # Perform a deep sync (90 days)
            run_etl(user_id=user_id, days_back=90)
            # Update Firestore flag on success
            update_user_profile(user_id, {"full_etl_synced": True})
            log.info(f"✅ Background ETL: Historical sync complete for {user_id}.")

            # Send a welcome notification
            msg = (
                "👋 *Welcome to the platform!* I've finished importing your last 90 days of Garmin history. "
                "I'm now ready to provide precision training advice based on your full physiological profile."
            )
            send_proactive_notification(user_id, msg)
        except Exception as e:
            log.error(f"❌ Background ETL failed for {user_id}: {e}")

    threading.Thread(target=backfill_task, daemon=True).start()
