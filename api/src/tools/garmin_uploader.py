import logging
from typing import Literal, Union, Optional, Any, cast

from garmin_training_toolkit_sdk.protocol.workouts import WorkoutPlan
from garmin_training_toolkit_sdk.uploaders.calendar import clear_calendar_range
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.provider_factory import get_provider

log = logging.getLogger(__name__)

# --- New Strongly Typed Targets ---

class HeartRateTarget(BaseModel):
    target_type: Literal["heart.rate"] = "heart.rate"
    min_bpm: int
    max_bpm: int

class PaceTarget(BaseModel):
    target_type: Literal["pace"] = "pace"
    min_pace_seconds: int  # e.g., 240 for 4:00/km
    max_pace_seconds: int

class PowerTarget(BaseModel):
    target_type: Literal["power"] = "power"
    min_watts: int
    max_watts: int

class LegacyTarget(BaseModel):
    """Backward compatibility for existing target format."""
    target_type: str | None = None
    min_target: float | None = None
    max_target: float | None = None

# --- Workout Models ---

class WorkoutStep(BaseModel):
    type: str  # e.g., 'run', 'recovery', 'interval', 'warmup', 'cooldown'
    duration_mins: Optional[float] = None
    distance_m: Optional[int] = None
    duration: Optional[float] = None  # Legacy support (minutes)
    target: Union[HeartRateTarget, PaceTarget, PowerTarget, LegacyTarget, None] = None

class RepeatGroup(BaseModel):
    type: Literal["repeat"] = "repeat"
    iterations: int
    steps: list[WorkoutStep]

class Workout(BaseModel):
    name: str
    description: str = ""
    duration: float  # Total estimated duration in minutes
    date: str
    # A workout can consist of individual steps or repeated groups of steps
    steps: list[Union[WorkoutStep, RepeatGroup]]

class TrainingPlan(BaseModel):
    workouts: list[Workout]

@tool(args_schema=TrainingPlan)
def upload_training_plan(workouts: list[Workout]):
    """Uploads a training plan with support for repeats, distances, and typed targets."""
    log.info(f"📤 Uploading {len(workouts)} workouts via Provider...")
    provider = get_provider()

    try:
        # The SDK's WorkoutPlan will now handle the mapping of these new structures
        plan_data = [w.model_dump(exclude_none=True) for w in workouts]
        workout_plan = WorkoutPlan(root=cast(Any, plan_data))

        report = provider.upload_training_plan(workout_plan)
        if report.success:
            return f"Success: {report.message}. IDs: {', '.join(report.uploaded_ids)}"
        return f"Failed: {report.message}"
    except Exception as e:
        log.error(f"❌ Upload failed: {e}")
        return f"Error: {e}"

# --- Other Tools ---

class CalendarRange(BaseModel):
    start_date: str
    end_date: str

@tool(args_schema=CalendarRange)
def clear_calendar(start_date: str, end_date: str):
    """Clears calendar range for the active provider."""
    log.info("🧹 Clearing Calendar...")
    provider = get_provider()
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
        client = getattr(provider, "client", None)
        if client:
            client.delete_workout(workout_id)
            return f"Successfully deleted workout {workout_id}."
        return "Provider does not support direct workout deletion."
    except Exception as e:
        log.error(f"❌ Failed to delete workout {workout_id}: {e}")
        return f"Error deleting workout {workout_id}: {e}"
