import logging
import os
import sys

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Add the project root to sys.path
sys.path.append(os.getcwd())

from src.agent.proactive import run_proactive_analysis

if __name__ == "__main__":
    user_id = "fsirio"
    print(f"🚀 Manually triggering proactive analysis for user: {user_id}")
    run_proactive_analysis(user_id)
    print("✅ Done.")
