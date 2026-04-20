import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_sql
from memory.sql.sql_manager import SQLManager


# --- Schemas ---

class CreateUserRequest(BaseModel):
    name: str
    age: int
    height_cm: float
    weight_kg: float
    gender: Optional[str] = None


class CreateGoalRequest(BaseModel):
    goal_type: str
    description: str
    target_date: Optional[datetime.date] = None


class GoalResponse(BaseModel):
    id: int
    goal_type: str
    description: str
    target_date: Optional[datetime.date]
    status: str
    created_at: datetime.datetime


class UserResponse(BaseModel):
    id: str
    name: str
    age: int
    gender: Optional[str]
    height_cm: float
    weight_kg: float
    created_at: datetime.datetime
    goals: List[GoalResponse]


# --- Router ---

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(body: CreateUserRequest, sql: SQLManager = Depends(get_sql)) -> UserResponse:
    user = sql.create_user(
        name=body.name,
        age=body.age,
        height_cm=body.height_cm,
        weight_kg=body.weight_kg,
        gender=body.gender,
    )
    return UserResponse(goals=[], **user.to_dict())


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, sql: SQLManager = Depends(get_sql)) -> UserResponse:
    user = sql.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    goals = sql.get_user_goals(user_id)
    return UserResponse(goals=[GoalResponse(**g.to_dict()) for g in goals], **user.to_dict())


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, sql: SQLManager = Depends(get_sql)) -> None:
    deleted = sql.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")


@router.post("/{user_id}/goals", response_model=GoalResponse, status_code=201)
def add_goal(user_id: str, body: CreateGoalRequest, sql: SQLManager = Depends(get_sql)) -> GoalResponse:
    if sql.get_user(user_id) is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    goal = sql.create_goal(
        user_id=user_id,
        goal_type=body.goal_type,
        description=body.description,
        target_date=body.target_date,
    )
    return GoalResponse(**goal.to_dict())


@router.delete("/{user_id}/goals/{goal_id}", status_code=204)
def delete_goal(user_id: str, goal_id: int, sql: SQLManager = Depends(get_sql)) -> None:
    if not sql.delete_goal(goal_id):
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found.")
