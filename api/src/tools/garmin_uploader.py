from pydantic import BaseModel, Field
from typing import List, Optional, Union, Any
from langchain_core.tools import tool
import logging
from datetime import datetime
from garmin_training_toolkit_sdk.utils import get_authenticated_client, find_token_file
from garmin_training_toolkit_sdk.uploaders.workouts import create_workout

log = logging.getLogger(__name__)

class WorkoutTarget(BaseModel):
    workoutTargetTypeId: int = Field(description="4 for HEART_RATE, 5 for SPEED/PACE")
    workoutTargetTypeKey: str = Field(description="'heart.rate.zone' or 'speed.zone'")
    displayOrder: int = Field(default=1)
    zone: Optional[Union[dict, str, int]] = Field(description="Zone definition: e.g., {'low': 140, 'high': 160} or just the zone number/string.")
    targetValueOne: Optional[float] = None
    targetValueTwo: Optional[float] = None

class WorkoutStep(BaseModel):
    type: str = Field(description="Step type: 'warmup', 'run', 'recovery', 'cooldown'")
    duration_sec: Optional[int] = Field(None, description="Duration in seconds")
    duration_dist: Optional[int] = Field(None, description="Duration in meters")
    target: Optional[WorkoutTarget] = Field(description="Target pace or HR zone")

class Workout(BaseModel):
    name: str = Field(description="Name of the workout")
    description: str = Field(description="Description of the workout")
    date: str = Field(description="Target date in YYYY-MM-DD format")
    steps: List[WorkoutStep] = Field(description="List of steps in the workout")

class TrainingPlan(BaseModel):
    workouts: List[Workout] = Field(description="List of workouts for the training plan")

def get_client():
    token_file = find_token_file()
    if not token_file:
        raise Exception("Garmin authentication token not found. Please run authentication first.")
    return get_authenticated_client(token_file)

@tool(args_schema=TrainingPlan)
def upload_workouts_to_garmin(workouts: List[Workout]):
    """
    Uploads a generated training plan (list of workouts) to the user's Garmin Calendar.
    Each workout is a structured object with steps and targets.
    Use this tool ONLY when the user asks to 'upload', 'sync', or 'put on calendar'.
    """
    log.info(f"📤 Uploading {len(workouts)} workouts to Garmin...")
    client = get_client()
    summary = []

    for w in workouts:
        # Map our Pydantic model to the format expected by SDK's create_workout
        # SDK expects: {"name": str, "description": str, "duration": int, "steps": [("type", val, target), ...]}
        sdk_steps = []
        total_duration = 0
        for s in w.steps:
            duration = s.duration_sec or s.duration_dist or 600
            total_duration += duration if s.duration_sec else 0
            
            target = None
            if s.target:
                if s.target.workoutTargetTypeId == 4: # HR
                    target = {"type": "heart.rate.zone", "zone": str(s.target.zone)}
                elif s.target.workoutTargetTypeId == 5: # SPEED
                    target = {"type": "speed.zone", "value": s.target.targetValueOne or 3.33}
            
            sdk_steps.append((s.type, duration, target))

        workout_data = {
            "name": w.name,
            "description": w.description,
            "duration": total_duration,
            "steps": sdk_steps
        }

        # Create RunningWorkout object using SDK
        garmin_workout = create_workout(workout_data)

        # Upload template
        uploaded = client.upload_running_workout(garmin_workout)
        workout_id = uploaded["workoutId"]

        # Schedule on calendar
        client.schedule_workout(workout_id, w.date)
        
        log.info(f"Successfully uploaded and scheduled: {w.name} on {w.date}")
        summary.append(f"{w.name} ({w.date})")

    return f"Successfully uploaded {len(workouts)} workouts to Garmin Calendar: {', '.join(summary)}."

class CalendarRange(BaseModel):
    start_date: str = Field(description="Start date in YYYY-MM-DD format")
    end_date: str = Field(description="End date in YYYY-MM-DD format")

@tool(args_schema=CalendarRange)
def clear_garmin_calendar(start_date: str, end_date: str):
    """
    Clears all scheduled workouts from the user's Garmin Calendar within a specific date range.
    Use this BEFORE uploading a new plan if the user wants to 'replace' or 'clean' their existing calendar.
    """
    log.info(f"🧹 Clearing Garmin Calendar from {start_date} to {end_date}...")
    client = get_client()
    
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Garmin API fetches by month. Iterate through all months in range.
    curr_year = start_dt.year
    curr_month = start_dt.month
    
    cleared_count = 0
    while (curr_year < end_dt.year) or (curr_year == end_dt.year and curr_month <= end_dt.month):
        log.info(f"Fetching scheduled workouts for {curr_year}-{curr_month:02d}...")
        cal_data = client.get_scheduled_workouts(curr_year, curr_month)
        
        if cal_data and "calendarItems" in cal_data:
            for item in cal_data["calendarItems"]:
                item_date_str = item.get("date")
                if not item_date_str: continue
                
                try:
                    item_date = datetime.strptime(item_date_str, "%Y-%m-%d")
                    if start_dt <= item_date <= end_dt:
                        scheduled_id = item.get("calendarItemId")
                        if scheduled_id:
                            log.info(f"Unscheduling workout {item.get('itemType')} on {item_date_str}...")
                            client.unschedule_workout(scheduled_id)
                            cleared_count += 1
                except ValueError:
                    continue
        
        # Move to next month
        curr_month += 1
        if curr_month > 12:
            curr_month = 1
            curr_year += 1
            
    return f"Successfully cleared {cleared_count} workouts from Garmin Calendar between {start_date} and {end_date}."
