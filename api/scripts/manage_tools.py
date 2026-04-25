import json
import logging
import os
import select
import sys
from typing import Any

# Configure logging to stderr to avoid polluting stdout
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

# Add src to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.tools.garmin_uploader import clear_garmin_calendar, upload_workouts_to_garmin
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data

# Mapping of names to LangChain tools
TOOLS = {
    "clear_garmin_calendar": clear_garmin_calendar,
    "upload_workouts_to_garmin": upload_workouts_to_garmin,
    "search_exercise_science": search_exercise_science,
    "retrieve_biometric_data": retrieve_biometric_data,
}


def list_tools():
    # Convert LangChain tool metadata to Gemini CLI expected format
    definitions = []
    for name, tool in TOOLS.items():
        parameters: dict[str, Any] = {}
        if hasattr(tool, "args_schema") and tool.args_schema:
            schema_obj = tool.args_schema
            if hasattr(schema_obj, "model_json_schema"):
                parameters = schema_obj.model_json_schema()
            elif hasattr(schema_obj, "schema"):
                parameters = schema_obj.schema()
        else:
            parameters = {"type": "object", "properties": {}}

        definitions.append({"name": name, "description": tool.description, "parameters": parameters})
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

        tool = TOOLS.get(name)
        if tool:
            result = tool.invoke(args)
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
