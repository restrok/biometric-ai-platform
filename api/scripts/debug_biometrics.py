"""Script to debug biometric data retrieval and serialization."""

import json
import sys
from datetime import date
from typing import Any

from src.tools.retriever import retrieve_biometric_data
from src.utils.config import setup_environment


def serialize_dates(obj: Any) -> Any:
    """Recursively serializes date objects to ISO format strings."""
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: serialize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_dates(elem) for elem in obj]
    return obj


def debug_biometrics() -> None:
    """Retrieves biometric data and prints it as JSON."""
    setup_environment()
    try:
        data = retrieve_biometric_data.invoke({})
        serialized_data = serialize_dates(data)
        print(json.dumps(serialized_data, indent=2))
    except Exception as e:
        print(f"Error retrieving biometric data: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    debug_biometrics()


if __name__ == "__main__":
    main()
