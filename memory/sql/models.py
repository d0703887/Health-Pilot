import datetime
import uuid
from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# --- MODELS ---

class Base(DeclarativeBase):
    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class User(Base):
    __tablename__ = 'users'

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str]
    age: Mapped[int]
    gender: Mapped[Optional[str]]
    height_cm: Mapped[float]
    weight_kg: Mapped[float]
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    # Relationships
    goals: Mapped[List["Goal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    nutrition: Mapped[List["Nutrition"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    workouts: Mapped[List["Workout"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sleep_records: Mapped[List["SleepData"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Goal(Base):
    __tablename__ = 'goals'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    goal_type: Mapped[str] = mapped_column(doc="e.g., 'Lean Bulk', 'Weight Loss', 'Maintenance'")
    description: Mapped[str]
    target_date: Mapped[Optional[datetime.date]]
    status: Mapped[str] = mapped_column(default="active", doc="'active', 'completed', 'abandoned'")
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="goals")


class Nutrition(Base):
    __tablename__ = 'nutrition'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    timestamp: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    # Added context fields to describe the specific intake
    food_name: Mapped[str] = mapped_column(doc="e.g., 'Chicken Breast', 'Protein Shake'")
    meal_type: Mapped[Optional[str]] = mapped_column(doc="e.g., 'Breakfast', 'Lunch', 'Dinner', 'Snack'")

    # Macros for this specific intake
    calories: Mapped[int]
    protein_g: Mapped[float]
    carbs_g: Mapped[float]
    fats_g: Mapped[float]

    user: Mapped["User"] = relationship(back_populates="nutrition")


class Workout(Base):
    __tablename__ = 'workouts'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    timestamp: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    activity_type: Mapped[str] = mapped_column(doc="e.g., 'Weightlifting', 'Running'")
    duration_minutes: Mapped[int]
    intensity: Mapped[Optional[str]] = mapped_column(doc="'Low', 'Moderate', 'High'")
    notes: Mapped[Optional[str]]

    user: Mapped["User"] = relationship(back_populates="workouts")


class SleepData(Base):
    __tablename__ = 'sleep_data'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    date: Mapped[datetime.date]
    duration_hours: Mapped[float]
    quality_score: Mapped[Optional[int]] = mapped_column(doc="0-100 score from wearables")
    sleep_stages_json: Mapped[Optional[str]] = mapped_column(doc="JSON string of deep/light/rem sleep")

    user: Mapped["User"] = relationship(back_populates="sleep_records")