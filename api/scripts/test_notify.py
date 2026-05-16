"""Script to test proactive notification delivery."""

import asyncio
import os

from dotenv import load_dotenv

from src.utils.notifications import send_proactive_notification


def test_notification() -> None:
    """Sends a test proactive notification to a specific user."""
    # Load .env from the current directory (api/)
    load_dotenv()

    # Mock environment if needed
    if not os.getenv("ORCHESTRATOR_NOTIFY_URL"):
        os.environ["ORCHESTRATOR_NOTIFY_URL"] = "http://localhost:8001/api/notify"

    user_id = "fsirio"
    message = "Test notification from Gemini CLI! The proactive infrastructure is now live. 🚀"

    print(f"Sending test notification to {user_id}...")
    success = send_proactive_notification(user_id, message)

    if success:
        print("✅ Success!")
    else:
        print("❌ Failed.")


def main() -> None:
    """Main entry point."""
    test_notification()


if __name__ == "__main__":
    main()
