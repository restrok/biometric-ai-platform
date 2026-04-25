import logging

from garmin_training_toolkit_sdk.uploaders.calendar import clear_calendar_range
from garmin_training_toolkit_sdk.protocol.workouts import WorkoutPlan
from src.utils.provider_factory import get_provider
from langchain_core.tools import tool
from pydantic import BaseModel

log = logging.getLogger(__name__)


class WorkoutTarget(BaseModel):
    displayOrder: int = 1
    target_type: str | None = None  # e.g., 'heart.rate.zone'
    min_target: float | None = None  # e.g., 145
    max_target: float | None = None  # e.g., 165


class WorkoutStep(BaseModel):
    type: str  # e.g., 'run', 'recovery', 'interval', 'warmup', 'cooldown'
    duration: float  # Duration in minutes (e.g. 10.5)
    target: WorkoutTarget | None = None


class Workout(BaseModel):
    name: str
    description: str = ""
    duration: float  # Total duration in minutes
    date: str
    steps: list[WorkoutStep]


class TrainingPlan(BaseModel):
    workouts: list[Workout]


@tool(args_schema=TrainingPlan)
def upload_training_plan(workouts: list[Workout]):
    """Uploads a training plan to the active biometric provider."""
    log.info(f"📤 Uploading {len(workouts)} workouts via Provider...")
    provider = get_provider()
    
    try:
        # Map our LangChain tool models to the SDK Protocol models
        plan_data = [w.model_dump() for w in workouts]
        workout_plan = WorkoutPlan(root=plan_data)
        
        report = provider.upload_training_plan(workout_plan)
        
        if report.success:
            return f"Success: {report.message}. IDs: {', '.join(report.uploaded_ids)}"
        return f"Failed: {report.message}"
    except Exception as e:
        log.error(f"❌ Upload failed: {e}")
        return f"Error: {e}"


class CalendarRange(BaseModel):
    start_date: str
    end_date: str


@tool(args_schema=CalendarRange)
def clear_calendar(start_date: str, end_date: str):
    """Clears calendar range for the active provider."""
    log.info("🧹 Clearing Calendar...")
    provider = get_provider()
    # Garmin-specific logic still relies on the underlying client for now
    client = getattr(provider, "client", None)
    if not client:
        return "Provider does not support direct calendar clearing."
    cleared_count = clear_calendar_range(client, start_date, end_date)
    return f"Successfully cleared {cleared_count} workouts."


class WorkoutID(BaseModel):
    workout_id: str


@tool(args_schema=WorkoutID)
def remove_workout(workout_id: str):
    """Deletes a specific workout using the active provider."""
    log.info(f"🗑️ Deleting workout {workout_id}...")
    provider = get_provider()
    try:
        # Garmin-specific logic
        client = getattr(provider, "client", None)
        if client:
            client.delete_workout(workout_id)
            return f"Successfully deleted workout {workout_id}."
        return "Provider does not support direct workout deletion."
    except Exception as e:
        log.error(f"❌ Failed to delete workout {workout_id}: {e}")
        return f"Error deleting workout {workout_id}: {e}"
