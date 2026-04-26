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
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")

class WorkoutTarget(BaseModel):
    displayOrder: int = 1
    target_type: Optional[str] = None
    min_target: Optional[float] = None
    max_target: Optional[float] = None

class WorkoutStep(BaseModel):
    type: str
    duration: float
    target: Optional[WorkoutTarget] = None

class Workout(BaseModel):
    name: str
    description: str = ""
    duration: float
    date: str
    steps: list[WorkoutStep]

class TrainingPlan(BaseModel):
    workouts: list[Workout]

class WorkoutID(BaseModel):
    workout_id: str

class ZoneUpdate(BaseModel):
    z1_max: int
    z2_max: int
    z3_max: int
    z4_max: int

class ActivityID(BaseModel):
    activity_id: str

class SearchQuery(BaseModel):
    query: str

class RetrieverInput(BaseModel):
    project_id: Optional[str] = None
    dataset: Optional[str] = None

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
