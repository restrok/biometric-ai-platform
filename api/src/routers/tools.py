import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Import tools
from src.tools.analytics import analyze_activity_efficiency
from src.tools.etl_tool import sync_biometric_data
from src.tools.garmin_uploader import clear_calendar, remove_workout, upload_training_plan
from src.tools.profile_manager import update_user_zones
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data
from src.utils.garmin_auth import refresh_garmin_session
from garmin_training_toolkit_sdk.utils import find_token_file

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])

# --- Request Models ---

class CalendarRange(BaseModel):
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format", examples=["2026-04-26"])
    end_date: str = Field(..., description="End date in YYYY-MM-DD format", examples=["2026-04-27"])

class WorkoutTarget(BaseModel):
    displayOrder: int = Field(1, description="Order in which this target is displayed in the workout step.")
    target_type: Optional[str] = Field(None, description="Must be one of: 'heart.rate.zone', 'pace.zone', or 'power.zone'.", examples=["heart.rate.zone"])
    min_target: Optional[float] = Field(None, description="Minimum value for the target (e.g., min bpm or min watts).", examples=[145.0])
    max_target: Optional[float] = Field(None, description="Maximum value for the target (e.g., max bpm or max watts).", examples=[165.0])

class WorkoutStep(BaseModel):
    type: str = Field(..., description="Type of exercise step: 'run', 'warmup', 'cooldown', 'recovery', or 'interval'.", examples=["run"])
    duration: float = Field(..., description="Duration of the step in minutes.", examples=[60.0])
    target: Optional[WorkoutTarget] = Field(None, description="Optional intensity target for this step.")

class Workout(BaseModel):
    name: str = Field(..., description="Descriptive name of the workout.", examples=["Z2 Base Run"])
    description: str = Field("", description="Detailed instructions for the athlete.", examples=["60 mins at Aerobic Threshold"])
    duration: float = Field(..., description="Total estimated duration in minutes.", examples=[60.0])
    date: str = Field(..., description="Scheduled date in YYYY-MM-DD format.", examples=["2026-04-26"])
    steps: list[WorkoutStep] = Field(..., description="Ordered list of workout steps.")

class TrainingPlan(BaseModel):
    workouts: list[Workout] = Field(..., description="List of workouts to be uploaded and scheduled.")

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
    query: str = Field(..., description="The natural language question about exercise science to search for.", examples=["What are the benefits of polarized training?"])

class RetrieverInput(BaseModel):
    project_id: Optional[str] = Field(None, description="GCP Project ID. Defaults to environment config if not provided.")
    dataset: Optional[str] = Field(None, description="BigQuery Dataset ID. Defaults to environment config if not provided.")

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
    """Uploads a training plan to the active biometric provider."""
    try:
        result = upload_training_plan.invoke(req.model_dump())
        if "Failed" in result or "Error" in result:
            raise Exception(result)
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

@router.post("/session/refresh")
async def api_refresh_session():
    """Manually triggers a session refresh for the biometric provider (e.g. Garmin)."""
    try:
        token_file = find_token_file()
        if not token_file:
            return {"status": "error", "message": "Token file not found."}
        
        if refresh_garmin_session(token_file):
            return {"status": "success", "message": "Successfully refreshed biometric session."}
        else:
            return {"status": "error", "message": "Failed to refresh session."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
