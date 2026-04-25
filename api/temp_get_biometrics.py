import json
from datetime import date
from src.tools.retriever import retrieve_biometric_data
import os
import sys

# Ensure environment is set up if not already
if not os.getenv("GOOGLE_CLOUD_PROJECT"):
    from src.utils.config import setup_environment
    setup_environment()

def serialize_dates(obj):
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: serialize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_dates(elem) for elem in obj]
    return obj

try:
    data = retrieve_biometric_data()
    serialized_data = serialize_dates(data)
    print(json.dumps(serialized_data, indent=2))
except Exception as e:
    print(f"Error retrieving biometric data: {e}", file=sys.stderr)
    sys.exit(1)
