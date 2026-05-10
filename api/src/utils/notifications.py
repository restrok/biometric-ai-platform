import logging
import os
import httpx

log = logging.getLogger("api.notifications")

def send_proactive_notification(user_id: str, message: str, agent_id: str = "biometric-coach"):
    """
    Sends a notification to the user via the Telegram Agent Orchestrator.
    (Synchronous version for use in background executors)
    """
    notify_url = os.getenv("ORCHESTRATOR_NOTIFY_URL")
    if not notify_url:
        log.warning("⚠️ ORCHESTRATOR_NOTIFY_URL not set. Notification skipped.")
        return False

    payload = {
        "user_id": user_id,
        "agent_id": agent_id,
        "message": message
    }

    try:
        with httpx.Client() as client:
            response = client.post(notify_url, json=payload, timeout=10.0)
            if response.status_code == 200:
                log.info(f"✅ Notification sent to {user_id} via {notify_url}")
                return True
            else:
                log.error(f"❌ Failed to send notification: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        log.error(f"❌ Exception sending notification: {e}")
        return False
