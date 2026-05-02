import logging
from typing import Any, Literal, cast

from garmin_training_toolkit_sdk.protocol.workouts import WorkoutPlan
from langchain_core.tools import tool
from pydantic import BaseModel

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
    duration_mins: float | None = None
    distance_m: int | None = None
    duration: float | None = None  # Legacy support (minutes)
    target: HeartRateTarget | PaceTarget | PowerTarget | LegacyTarget | None = None


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
    steps: list[WorkoutStep | RepeatGroup]


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
    log.info(f"🧹 Clearing Calendar from {start_date} to {end_date}...")
    provider = get_provider()
    
    try:
        from datetime import datetime
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        # Use the new robust SDK method that handles month boundaries
        items = provider.get_calendar_range(s_date, e_date)
        
        cleared_count = 0
        for item in items:
            if item.get("itemType") == "workout":
                item_id = item.get("calendarItemId") or item.get("id")
                if not item_id:
                    continue
                
                # Use the standardized unschedule_workout method
                provider.unschedule_workout(str(item_id))
                cleared_count += 1
        
        return f"Successfully cleared {cleared_count} workouts."
    except Exception as e:
        log.error(f"❌ Failed to clear calendar: {e}")
        return f"Error: {e}"


class WorkoutID(BaseModel):
    workout_id: str


@tool(args_schema=WorkoutID)
def remove_workout(workout_id: str):
    """Deletes a specific workout template using the active provider."""
    log.info(f"🗑️ Deleting workout template {workout_id}...")
    provider = get_provider()
    try:
        # Use the standardized delete_workout_template method
        provider.delete_workout_template(workout_id)
        return f"Successfully deleted workout template {workout_id}."
    except Exception as e:
        log.error(f"❌ Failed to delete workout {workout_id}: {e}")
        return f"Error deleting workout {workout_id}: {e}"
