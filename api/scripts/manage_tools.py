import json
import logging
import os
import sys
from typing import Any

# Configure logging to stderr to avoid polluting stdout
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

# Add src to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from garmin_training_toolkit_sdk.utils import find_token_file
from langchain_core.tools import tool

from src.tools.analytics import analyze_activity_efficiency
from src.tools.etl_tool import sync_biometric_data
from src.tools.garmin_uploader import clear_calendar, remove_workout, upload_training_plan
from src.tools.profile_manager import update_user_zones
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data
from src.utils.garmin_auth import refresh_garmin_session


@tool
def refresh_biometric_session():
    """
    Manually triggers a session refresh for the biometric provider (e.g. Garmin).
    Use this if you encounter 401 Unauthorized errors or if the user explicitly
    asks to 'fix the connection' or 'refresh the token'.
    """
    token_file = find_token_file()
    if not token_file:
        return "Error: Token file not found. Manual authentication required."

    if refresh_garmin_session(token_file):
        return "Successfully refreshed biometric session."
    return "Failed to refresh session. All client IDs exhausted. Manual login may be required."


# Mapping of names to LangChain tools
TOOLS = {
    "clear_calendar": clear_calendar,
    "upload_training_plan": upload_training_plan,
    "remove_workout": remove_workout,
    "update_user_zones": update_user_zones,
    "sync_biometric_data": sync_biometric_data,
    "analyze_activity_efficiency": analyze_activity_efficiency,
    "search_exercise_science": search_exercise_science,
    "retrieve_biometric_data": retrieve_biometric_data,
    "refresh_biometric_session": refresh_biometric_session,
}


def list_tools():
    # Convert LangChain tool metadata to Gemini CLI expected format
    definitions = []
    for name, tool_obj in TOOLS.items():
        parameters: dict[str, Any] = {}
        if hasattr(tool_obj, "args_schema") and tool_obj.args_schema:
            schema_obj = tool_obj.args_schema
            if hasattr(schema_obj, "model_json_schema"):
                parameters = schema_obj.model_json_schema()
            elif hasattr(schema_obj, "schema"):
                parameters = schema_obj.schema()
        else:
            parameters = {"type": "object", "properties": {}}

        definitions.append({"name": name, "description": tool_obj.description, "parameters": parameters})
    # Print only JSON to stdout
    print(json.dumps(definitions))


def call_tool(name):
    try:
        # Read from stdin if there is data available
        if not sys.stdin.isatty():
            args_str = sys.stdin.read().strip()
            # logging.error(f"Read from stdin: {args_str}") # Debug
            args = json.loads(args_str) if args_str else {}
        else:
            args = {}

        tool_obj = TOOLS.get(name)
        if tool_obj:
            result = tool_obj.invoke(args)
            if not isinstance(result, (str, dict, list, int, float, bool, type(None))):
                result = str(result)
            print(json.dumps(result))
        else:
            print(json.dumps({"error": f"Tool '{name}' not found"}), file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    command = sys.argv[1]
    if command == "list":
        list_tools()
    elif command == "call":
        if len(sys.argv) < 3:
            sys.exit(1)
        call_tool(sys.argv[2])
    else:
        sys.exit(1)
