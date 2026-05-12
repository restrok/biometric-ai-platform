import os
import sys

import httpx
from dotenv import load_dotenv


def send_custom(message):
    # Load config from the local .env
    load_dotenv("/app/.env")
    url = os.getenv("ORCHESTRATOR_NOTIFY_URL")

    if not url:
        print("❌ Error: ORCHESTRATOR_NOTIFY_URL not found in .env")
        return

    payload = {"user_id": "fsirio", "agent_id": "biometric-coach", "message": message}

    try:
        resp = httpx.post(url, json=payload, timeout=10.0)
        if resp.status_code == 200:
            print(f"✅ Mensaje enviado exitosamente a {url}")
        else:
            print(f"❌ Error del Orchestrator ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"❌ Falló la conexión: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 send_msg.py 'Tu mensaje aquí'")
    else:
        send_custom(sys.argv[1])
