import json
import logging
import os
import sys
from typing import Any

# Configure logging to stderr to avoid polluting stdout
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

# Add src to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.tools.garmin_uploader import clear_garmin_calendar, upload_workouts_to_garmin
from src.tools.research_assistant import search_exercise_science

# Mapping of names to LangChain tools
TOOLS = {
    "clear_garmin_calendar": clear_garmin_calendar,
    "upload_workouts_to_garmin": upload_workouts_to_garmin,
    "search_exercise_science": search_exercise_science,
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
        if not sys.stdin.isatty():
            args_str = sys.stdin.read()
            args = {} if not args_str else json.loads(args_str)
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
