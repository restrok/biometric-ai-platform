"""Script to manually trigger proactive analysis for a user."""

import logging

from src.agent.proactive import run_proactive_analysis


def test_proactive() -> None:
    """Triggers the proactive analysis workflow."""
    # Configure logging to see what's happening
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    user_id = "fsirio"
    print(f"🚀 Manually triggering proactive analysis for user: {user_id}")
    run_proactive_analysis(user_id)
    print("✅ Done.")


def main() -> None:
    """Main entry point."""
    test_proactive()


if __name__ == "__main__":
    main()
