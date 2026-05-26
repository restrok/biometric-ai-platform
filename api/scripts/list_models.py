import os
import logging
from google import genai
from langchain_core.tools import tool
from src.utils.config import get_config, setup_environment

log = logging.getLogger(__name__)

@tool
def list_available_models() -> list[str]:
    """
    Lists all available models in the Google GenAI API.
    Useful for diagnostics when a specific model version is deprecated or unavailable.
    """
    setup_environment()
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return ["Error: GOOGLE_API_KEY not found in environment."]

    try:
        client = genai.Client(api_key=api_key)
        models = client.models.list()
        # Return simple slugs like 'gemini-2.0-flash' instead of 'models/gemini-2.0-flash'
        return [m.name.replace("models/", "") for m in models]
    except Exception as e:
        log.error(f"Failed to list models: {e}")
        return [f"Error listing models: {str(e)}"]

if __name__ == "__main__":
    # If run as a script, just print the list
    setup_environment()
    models = list_available_models.invoke({})
    print("\n--- Available Google GenAI Models ---")
    for m in models:
        print(f"  - {m}")
    print("-------------------------------------\n")
