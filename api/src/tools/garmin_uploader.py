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
    type: Literal["warmup", "run", "recovery", "cooldown", "interval"]
    duration_mins: float | None = None
    distance_m: int | None = None
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
    user_id: str | None = None


@tool(args_schema=TrainingPlan)
def upload_training_plan(workouts: list[Workout], user_id: str | None = None):
    """Uploads a training plan with support for repeats, distances, and typed targets."""
    log.info(f"📤 Uploading {len(workouts)} workouts via Provider (user: {user_id})...")

    # DEBUG: Print the payload being sent to the SDK
    import json

    log.debug(f"DEBUG: Workout payload: {json.dumps([w.model_dump(exclude_none=True) for w in workouts], indent=2)}")

    provider = get_provider(user_id=user_id, refresh=True)

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
    user_id: str | None = None


@tool(args_schema=CalendarRange)
def clear_calendar(start_date: str, end_date: str, user_id: str | None = None):
    """Clears calendar range for the active provider."""
    log.info(f"🧹 Clearing Calendar from {start_date} to {end_date} (user: {user_id})...")

    provider = get_provider(user_id=user_id, refresh=True)

    try:
        from datetime import datetime

        s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date()

        # Use the new robust SDK method that handles month boundaries
        items = provider.get_calendar_range(s_date, e_date)

        cleared_count = 0
        for item in items:
            if item.get("itemType") == "workout":
                item_date_str = item.get("date")
                if item_date_str:
                    try:
                        item_date = datetime.strptime(item_date_str, "%Y-%m-%d").date()
                        # Strict date check: only clear if within requested range
                        if not (s_date <= item_date <= e_date):
                            continue
                    except ValueError:
                        log.warning(f"Could not parse date for calendar item: {item_date_str}")

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
    user_id: str | None = None


@tool(args_schema=WorkoutID)
def remove_workout(workout_id: str, user_id: str | None = None):
    """Deletes a specific workout template using the active provider."""
    log.info(f"🗑️ Deleting workout template {workout_id} (user: {user_id})...")
    provider = get_provider(user_id=user_id)
    try:
        # Use the standardized delete_workout_template method
        provider.delete_workout_template(workout_id)
        return f"Successfully deleted workout template {workout_id}."
    except Exception as e:
        log.error(f"❌ Failed to delete workout {workout_id}: {e}")
        return f"Error deleting workout {workout_id}: {e}"


class WorkoutListInput(BaseModel):
    user_id: str | None = None


@tool(args_schema=WorkoutListInput)
def list_workouts(user_id: str | None = None):
    """Lists all workouts in the user's Garmin library using the official SDK interface."""
    log.info(f"📋 Listing workouts for user: {user_id}...")
    provider = get_provider(user_id=user_id)
    try:
        # Using the new official SDK method
        templates = provider.get_workout_templates()
        result = []
        for t in templates:
            result.append(
                {
                    "workoutId": t.workout_id,
                    "workoutName": t.workout_name,
                    "sportType": t.sport_type,
                    "createdDate": t.created_date.isoformat() if t.created_date else None,
                    "description": t.description,
                }
            )
        return result
    except Exception as e:
        log.error(f"❌ Failed to list workouts: {e}")
        return f"Error: {e}"


class BatchWorkoutID(BaseModel):
    workout_ids: list[str]
    user_id: str | None = None


@tool(args_schema=BatchWorkoutID)
def batch_remove_workouts(workout_ids: list[str], user_id: str | None = None):
    """Deletes multiple workout templates in a single batch operation."""
    log.info(f"🗑️ Batch deleting {len(workout_ids)} workout templates (user: {user_id})...")
    provider = get_provider(user_id=user_id)
    success_count = 0
    errors = []

    for wid in workout_ids:
        try:
            provider.delete_workout_template(wid)
            success_count += 1
        except Exception as e:
            errors.append(f"ID {wid}: {e}")

    result = f"Successfully deleted {success_count} / {len(workout_ids)} workouts."
    if errors:
        result += f" Errors: {'; '.join(errors)}"
    return result


@tool(args_schema=WorkoutListInput)
def prune_unused_workouts(user_id: str | None = None):
    """
    Deletes workout templates that are not currently scheduled in the calendar.
    Scans the next 30 days of the calendar to identify active workout IDs.
    """
    log.info(f"✂️ Pruning unused workouts for user: {user_id}...")

    provider = get_provider(user_id=user_id, refresh=True)
    try:
        from datetime import date, timedelta

        # 1. Get all templates in the library
        templates = provider.get_workout_templates()
        all_ids = {str(t.workout_id) for t in templates}

        # 2. Get all scheduled workouts for the next 30 days
        start = date.today()
        end = start + timedelta(days=30)
        calendar_items = provider.get_calendar_range(start, end)

        scheduled_ids = set()
        for item in calendar_items:
            # We look for the workoutId associated with the calendar item
            wid = item.get("workoutId") or item.get("id")
            if item.get("itemType") == "workout" and wid:
                scheduled_ids.add(str(wid))

        # 3. Identify IDs to delete (those in library but NOT in calendar)
        # Note: We skip Garmin proprietary ones by logic if needed,
        # but usually user templates are the ones we want to prune.
        to_delete = all_ids - scheduled_ids

        if not to_delete:
            return "No unused workouts found. Your library is already clean."

        success_count = 0
        errors = []
        for wid in to_delete:
            try:
                provider.delete_workout_template(wid)
                success_count += 1
            except Exception as e:
                errors.append(f"ID {wid}: {e}")

        result = f"Pruned {success_count} unused workouts. Library IDs kept: {len(scheduled_ids)}."
        if errors:
            result += f" Errors: {len(errors)} failed to delete."
        return result

    except Exception as e:
        log.error(f"❌ Failed to prune workouts: {e}")
        return f"Error: {e}"
