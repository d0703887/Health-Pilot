import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_sql
from memory.sql.sql_manager import SQLManager


# --- Schemas ---

class NutritionRecord(BaseModel):
    id: int
    food_name: str
    meal_type: Optional[str]
    calories: int
    protein_g: float
    carbs_g: float
    fats_g: float
    timestamp: datetime.datetime


class UpdateNutritionRequest(BaseModel):
    food_name: Optional[str] = None
    meal_type: Optional[str] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fats_g: Optional[float] = None


class WorkoutRecord(BaseModel):
    id: int
    activity_type: str
    duration_minutes: int
    intensity: Optional[str]
    notes: Optional[str]
    timestamp: datetime.datetime


class UpdateWorkoutRequest(BaseModel):
    activity_type: Optional[str] = None
    duration_minutes: Optional[int] = None
    intensity: Optional[str] = None
    notes: Optional[str] = None


class SleepRecord(BaseModel):
    id: int
    date: datetime.date
    duration_hours: float
    quality_score: Optional[int]


class UpdateSleepRequest(BaseModel):
    date: Optional[datetime.date] = None
    duration_hours: Optional[float] = None
    quality_score: Optional[int] = None


# --- Router ---

router = APIRouter(prefix="/api/v1/users", tags=["records"])


# ── Nutrition ──────────────────────────────────────────────────────────────

@router.get("/{user_id}/nutrition", response_model=List[NutritionRecord])
def get_nutrition(user_id: str, sql: SQLManager = Depends(get_sql)):
    return [NutritionRecord(**r.to_dict()) for r in sql.get_user_nutrition(user_id)]


@router.patch("/{user_id}/nutrition/{record_id}", response_model=NutritionRecord)
def update_nutrition(user_id: str, record_id: int, body: UpdateNutritionRequest, sql: SQLManager = Depends(get_sql)):
    updates = body.model_dump(exclude_none=True)
    record = sql.update_nutrition(record_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Nutrition record {record_id} not found.")
    return NutritionRecord(**record.to_dict())


@router.delete("/{user_id}/nutrition/{record_id}", status_code=204)
def delete_nutrition(user_id: str, record_id: int, sql: SQLManager = Depends(get_sql)):
    if not sql.delete_nutrition(record_id):
        raise HTTPException(status_code=404, detail=f"Nutrition record {record_id} not found.")


# ── Workouts ───────────────────────────────────────────────────────────────

@router.get("/{user_id}/workouts", response_model=List[WorkoutRecord])
def get_workouts(user_id: str, sql: SQLManager = Depends(get_sql)):
    return [WorkoutRecord(**r.to_dict()) for r in sql.get_user_workouts(user_id)]


@router.patch("/{user_id}/workouts/{record_id}", response_model=WorkoutRecord)
def update_workout(user_id: str, record_id: int, body: UpdateWorkoutRequest, sql: SQLManager = Depends(get_sql)):
    updates = body.model_dump(exclude_none=True)
    record = sql.update_workout(record_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Workout record {record_id} not found.")
    return WorkoutRecord(**record.to_dict())


@router.delete("/{user_id}/workouts/{record_id}", status_code=204)
def delete_workout(user_id: str, record_id: int, sql: SQLManager = Depends(get_sql)):
    if not sql.delete_workout(record_id):
        raise HTTPException(status_code=404, detail=f"Workout record {record_id} not found.")


# ── Sleep ──────────────────────────────────────────────────────────────────

@router.get("/{user_id}/sleep", response_model=List[SleepRecord])
def get_sleep(user_id: str, sql: SQLManager = Depends(get_sql)):
    return [SleepRecord(**r.to_dict()) for r in sql.get_user_sleep_data(user_id)]


@router.patch("/{user_id}/sleep/{record_id}", response_model=SleepRecord)
def update_sleep(user_id: str, record_id: int, body: UpdateSleepRequest, sql: SQLManager = Depends(get_sql)):
    updates = body.model_dump(exclude_none=True)
    record = sql.update_sleep_data(record_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Sleep record {record_id} not found.")
    return SleepRecord(**record.to_dict())


@router.delete("/{user_id}/sleep/{record_id}", status_code=204)
def delete_sleep(user_id: str, record_id: int, sql: SQLManager = Depends(get_sql)):
    if not sql.delete_sleep_data(record_id):
        raise HTTPException(status_code=404, detail=f"Sleep record {record_id} not found.")
