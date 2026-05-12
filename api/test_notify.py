import asyncio
import os
import sys

from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from utils.notifications import send_proactive_notification


async def test_notification():
    # Load .env from the current directory (api/)
    load_dotenv()

    user_id = "fsirio"
    message = "Test notification from Gemini CLI! The proactive infrastructure is now live. 🚀"

    print(f"Sending test notification to {user_id}...")
    success = await send_proactive_notification(user_id, message)

    if success:
        print("✅ Success!")
    else:
        print("❌ Failed.")


if __name__ == "__main__":
    # Mock environment if needed
    if not os.getenv("ORCHESTRATOR_NOTIFY_URL"):
        os.environ["ORCHESTRATOR_NOTIFY_URL"] = "http://localhost:8001/api/notify"

    asyncio.run(test_notification())
