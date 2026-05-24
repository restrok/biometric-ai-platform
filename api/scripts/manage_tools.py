import asyncio
import json
import logging
import os
import sys
from typing import Any

# Configure logging to stderr to avoid polluting stdout
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

# Add src to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


from src.tools.analytics import analyze_activity_efficiency
from src.tools.auth_tools import complete_garmin_auth, get_garmin_auth_url
from src.tools.data_scientist import execute_exploratory_query, get_bigquery_schema
from src.tools.deep_reporting import generate_deep_historical_report
from src.tools.etl_tool import sync_biometric_data
from src.tools.garmin_uploader import (
    batch_remove_workouts,
    clear_calendar,
    list_workouts,
    prune_unused_workouts,
    remove_workout,
    upload_training_plan,
)
from src.tools.historical_biometrics import generate_historical_report
from src.tools.profile_manager import (
    configure_proactive_coaching,
    log_health_status,
    manage_goals,
    update_user_zones,
)
from src.tools.read_report_artifact import read_report_artifact
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data

# Mapping of names to LangChain tools
TOOLS = {
    "clear_calendar": clear_calendar,
    "upload_training_plan": upload_training_plan,
    "remove_workout": remove_workout,
    "list_workouts": list_workouts,
    "batch_remove_workouts": batch_remove_workouts,
    "prune_unused_workouts": prune_unused_workouts,
    "update_user_zones": update_user_zones,
    "log_health_status": log_health_status,
    "manage_goals": manage_goals,
    "sync_biometric_data": sync_biometric_data,
    "analyze_activity_efficiency": analyze_activity_efficiency,
    "search_exercise_science": search_exercise_science,
    "retrieve_biometric_data": retrieve_biometric_data,
    "generate_historical_report": generate_historical_report,
    "generate_deep_historical_report": generate_deep_historical_report,
    "execute_exploratory_query": execute_exploratory_query,
    "get_bigquery_schema": get_bigquery_schema,
    "read_report_artifact": read_report_artifact,
    "get_garmin_auth_url": get_garmin_auth_url,
    "complete_garmin_auth": complete_garmin_auth,
    "configure_proactive_coaching": configure_proactive_coaching,
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
        # 1. Try to read from positional arguments (CLI)
        if len(sys.argv) > 3:
            args_str = sys.argv[3]
            args = json.loads(args_str)
        # 2. Fallback: Read from stdin if there is data available
        elif not sys.stdin.isatty():
            args_str = sys.stdin.read().strip()
            args = json.loads(args_str) if args_str else {}
        else:
            args = {}

        tool_obj = TOOLS.get(name)
        if tool_obj:
            # Handle both sync and async tools
            # In LangChain, async tools typically have a coroutine function or specific flags
            func = getattr(tool_obj, "func", None)
            is_async = asyncio.iscoroutinefunction(func) if func else False

            if is_async:
                result = asyncio.run(tool_obj.ainvoke(args))
            else:
                try:
                    result = tool_obj.invoke(args)
                except Exception as e:
                    if "does not support sync invocation" in str(e):
                        result = asyncio.run(tool_obj.ainvoke(args))
                    else:
                        raise e

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
