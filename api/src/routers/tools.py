import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Import tools
from src.tools.analytics import analyze_activity_efficiency
from src.tools.etl_tool import sync_biometric_data
from src.tools.garmin_uploader import clear_calendar, remove_workout, upload_training_plan
from src.tools.profile_manager import update_user_zones
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])

# --- New Strongly Typed Targets ---


class HeartRateTarget(BaseModel):
    target_type: Literal["heart.rate"] = "heart.rate"
    min_bpm: int = Field(..., examples=[145])
    max_bpm: int = Field(..., examples=[155])


class PaceTarget(BaseModel):
    target_type: Literal["pace"] = "pace"
    min_pace_seconds: int = Field(..., description="Min pace in seconds per km", examples=[240])
    max_pace_seconds: int = Field(..., description="Max pace in seconds per km", examples=[250])


class PowerTarget(BaseModel):
    target_type: Literal["power"] = "power"
    min_watts: int = Field(..., examples=[250])
    max_watts: int = Field(..., examples=[300])


class LegacyTarget(BaseModel):
    target_type: str | None = Field(None, description="Legacy key: 'heart.rate.zone', etc.")
    min_target: float | None = None
    max_target: float | None = None


# --- Workout Models ---


class WorkoutStep(BaseModel):
    type: str = Field(..., description="Step type: 'run', 'warmup', 'cooldown', 'recovery', 'interval'")
    duration_mins: float | None = Field(None, examples=[10.0])
    distance_m: int | None = Field(None, examples=[800])
    duration: float | None = Field(None, description="Legacy duration in minutes.")
    target: HeartRateTarget | PaceTarget | PowerTarget | LegacyTarget | dict | None = None


class RepeatGroup(BaseModel):
    type: Literal["repeat"] = "repeat"
    iterations: int = Field(..., gt=0, examples=[6])
    steps: list[WorkoutStep]


class Workout(BaseModel):
    name: str = Field(..., examples=["VO2 Max Intervals"])
    description: str = Field("", examples=["6x800m intervals"])
    duration: float = Field(..., description="Total estimated duration in minutes.", examples=[56.0])
    date: str = Field(..., description="YYYY-MM-DD", examples=["2026-04-27"])
    steps: list[WorkoutStep | RepeatGroup]


class TrainingPlan(BaseModel):
    workouts: list[Workout]


# --- Other Request Models ---


class CalendarRange(BaseModel):
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format", examples=["2026-04-26"])
    end_date: str = Field(..., description="End date in YYYY-MM-DD format", examples=["2026-04-27"])


class WorkoutID(BaseModel):
    workout_id: str = Field(..., description="The unique internal ID of the workout to be removed.")


class ZoneUpdate(BaseModel):
    z1_max: int = Field(..., description="Maximum heart rate for Zone 1 (Recovery).", examples=[144])
    z2_max: int = Field(..., description="Maximum heart rate for Zone 2 (Aerobic Base).", examples=[165])
    z3_max: int = Field(..., description="Maximum heart rate for Zone 3 (Gray Zone).", examples=[176])
    z4_max: int = Field(..., description="Maximum heart rate for Zone 4 (Threshold).", examples=[186])


class ActivityID(BaseModel):
    activity_id: str = Field(..., description="The unique ID of the activity (e.g., Garmin Activity ID) to analyze.")


class SearchQuery(BaseModel):
    query: str = Field(
        ..., description="Natural language science question.", examples=["Polarized training 80/20 rule"]
    )


class RetrieverInput(BaseModel):
    project_id: str | None = None
    dataset: str | None = None
    limit: int = 20
    offset: int = 0
    activity_type: str | None = None


# --- Endpoints ---


@router.post("/calendar/clear")
async def api_clear_calendar(req: CalendarRange):
    """Clears calendar range for the active provider."""
    try:
        result = clear_calendar.invoke(req.model_dump())
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/training_plan/upload")
async def api_upload_training_plan(req: TrainingPlan):
    """Uploads a training plan with support for repeats, distances, and typed targets."""
    try:
        # Use model_dump to ensure nested structures are converted to dicts correctly for the tool
        result = upload_training_plan.invoke(req.model_dump())
        if "Failed" in str(result) or "Error" in str(result):
            raise Exception(str(result))
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workout/remove")
async def api_remove_workout(req: WorkoutID):
    """Deletes a specific workout using the active provider."""
    try:
        result = remove_workout.invoke(req.model_dump())
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/zones/update")
async def api_update_zones(req: ZoneUpdate):
    """Updates the user's custom heart rate zones in BigQuery."""
    try:
        result = update_user_zones.invoke(req.model_dump())
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/biometric/sync")
async def api_sync_biometric():
    """Triggers an incremental synchronization of biometric data from the provider to BigQuery."""
    try:
        result = sync_biometric_data.invoke({})
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activity/analyze_efficiency")
async def api_analyze_efficiency(req: ActivityID):
    """Performs high-precision physiological analysis on a specific activity."""
    try:
        result = analyze_activity_efficiency.invoke(req.model_dump())
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/science/search")
async def api_search_science(req: SearchQuery):
    """Searches the internal knowledge base for exercise science principles."""
    try:
        result = search_exercise_science.invoke(req.model_dump())
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/biometric/retrieve")
async def api_retrieve_biometric(req: RetrieverInput):
    """Retrieves the user's latest biometric context from BigQuery."""
    try:
        result = retrieve_biometric_data.invoke(req.model_dump())
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
