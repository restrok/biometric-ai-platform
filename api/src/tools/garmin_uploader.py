import logging

from garmin_training_toolkit_sdk.uploaders.calendar import clear_calendar_range, schedule_workout
from garmin_training_toolkit_sdk.uploaders.workouts import create_workout
from garmin_training_toolkit_sdk.utils import find_token_file, get_authenticated_client
from langchain_core.tools import tool
from pydantic import BaseModel

log = logging.getLogger(__name__)

class WorkoutTarget(BaseModel):
    workoutTargetTypeId: int
    workoutTargetTypeKey: str
    displayOrder: int = 1
    zone: dict | str | int | None = None
    targetValueOne: float | None = None
    targetValueTwo: float | None = None

class WorkoutStep(BaseModel):
    type: str
    duration_sec: int | None = None
    duration_dist: int | None = None
    target: WorkoutTarget | None = None

class Workout(BaseModel):
    name: str
    description: str
    date: str
    steps: list[WorkoutStep]

class TrainingPlan(BaseModel):
    workouts: list[Workout]

def get_client():
    token_file = find_token_file()
    if not token_file:
        raise Exception("Garmin authentication token not found.")
    return get_authenticated_client(token_file)

@tool(args_schema=TrainingPlan)
def upload_workouts_to_garmin(workouts: list[Workout]):
    """Uploads workouts to Garmin Calendar."""
    log.info(f"📤 Uploading {len(workouts)} workouts...")
    client = get_client()
    summary = []

    for w in workouts:
        sdk_steps = []
        total_duration = 0
        for s in w.steps:
            duration = s.duration_sec or s.duration_dist or 600
            total_duration += duration if s.duration_sec else 0
            
            target_dict = None
            if s.target:
                # PRESERVE ALL FIELDS for the SDK to pick up
                target_dict = s.target.model_dump(exclude_none=True)
            
            sdk_steps.append({
                "type": s.type,
                "duration": duration,
                "target": target_dict
            })

        workout_data = {
            "name": w.name,
            "description": w.description,
            "duration": total_duration,
            "steps": sdk_steps
        }

        # create_workout in SDK now handles raw dicts
        garmin_workout = create_workout(workout_data)
        uploaded = client.upload_workout(garmin_workout)
        workout_id = uploaded["workoutId"]

        schedule_workout(client, workout_id, w.date)
        summary.append(f"{w.name} ({w.date})")

    return f"Successfully uploaded {len(workouts)} workouts: {', '.join(summary)}."

class CalendarRange(BaseModel):
    start_date: str
    end_date: str

@tool(args_schema=CalendarRange)
def clear_garmin_calendar(start_date: str, end_date: str):
    """Clears calendar range."""
    log.info("🧹 Clearing Garmin Calendar...")
    client = get_client()
    cleared_count = clear_calendar_range(client, start_date, end_date)
    return f"Successfully cleared {cleared_count} workouts."
