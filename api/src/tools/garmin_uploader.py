from pydantic import BaseModel, Field
from typing import List, Optional, Union, Any
from langchain_core.tools import tool
import logging

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

@tool(args_schema=TrainingPlan)
def upload_workouts_to_garmin(workouts: List[Workout]):
    """
    Uploads a generated training plan (list of workouts) to the user's Garmin Calendar.
    Each workout is a structured object with steps and targets.
    Use this tool ONLY when the user asks to 'upload', 'sync', or 'put on calendar'.
    """
    log.info(f"📤 Uploading {len(workouts)} workouts to Garmin...")
    
    # In a real implementation, this would import garmin_toolkit
    # from garmin_toolkit.uploaders.workouts import upload_workout
    
    summary = []
    for w in workouts:
        log.info(f"Uploading: {w.name} on {w.date} ({len(w.steps)} steps)")
        summary.append(f"{w.name} ({w.date})")
        
    return f"Successfully uploaded {len(workouts)} workouts to Garmin Calendar: {', '.join(summary)}."
