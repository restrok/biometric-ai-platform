from src.utils.provider_factory import get_provider
from datetime import datetime, timedelta
import json
import os
import sys

def export_telemetry(activity_id=None, user_id="fsirio"):
    provider = get_provider(user_id=user_id)
    
    if not activity_id:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=7)
        activities = provider.get_activities(start_date, end_date)
        if not activities:
            print("No activities found.")
            return
        latest_act = sorted(activities, key=lambda x: x.date, reverse=True)[0]
        activity_id = str(latest_act.id)
        name = latest_act.name
    else:
        name = f"Activity {activity_id}"

    print(f"Fetching telemetry for: {name} (ID: {activity_id})")
    
    telemetry = provider.get_telemetry(str(activity_id))
    if not telemetry or not telemetry.ticks:
        print("No telemetry found for this activity.")
        return
        
    data = [t.model_dump() for t in telemetry.ticks]
    output_path = f"/app/activity_{activity_id}_raw.json"
    with open(output_path, "w") as f:
        json.dump(data, f)
    
    print(f"Saved {len(data)} ticks to {output_path}")

if __name__ == "__main__":
    act_id = sys.argv[1] if len(sys.argv) > 1 else None
    export_telemetry(activity_id=act_id)
