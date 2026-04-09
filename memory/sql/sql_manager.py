from .models import Base, User, Goal, Nutrition, Workout, SleepData

import sqlalchemy
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from typing import List, Optional, Type, Any
import datetime

# TODO: Let agent update the database row?

# --- DATABASE MANAGER ---
class SQLManager:
    """
    Manages synchronous CRUD operations for the long-term PostgreSQL memory.
    Requires psycopg3 driver.
    Example URL: postgresql+psycopg://postgres:password@localhost:5432/health_db
    """
    def __init__(
            self,
            sql_engine: sqlalchemy.Engine,
    ):
        self.engine = sql_engine
        # self.engine = create_engine(
        #     settings.SQLALCHEMY_DATABASE_URI,
        #     echo=False,
        #     pool_size=5,
        #     max_overflow=10,
        #     pool_recycle=1800
        # )
        # Create all tables if they don't exist
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    # --- GENERIC HELPERS ---
    def _create(self, instance: Base) -> Base:
        with self.SessionLocal() as session:
            session.add(instance)
            session.commit()
            session.refresh(instance)
            return instance

    def _get(self, model: Type[Base], record_id: Any) -> Optional[Base]:
        with self.SessionLocal() as session:
            return session.get(model, record_id)

    def _update(self, model: Type[Base], record_id: Any, **kwargs) -> Optional[Base]:
        with self.SessionLocal() as session:
            record = session.get(model, record_id)
            if record:
                for key, value in kwargs.items():
                    setattr(record, key, value)
                session.commit()
                session.refresh(record)
                return record
            return None

    def _delete(self, model: Type[Base], record_id: Any) -> bool:
        with self.SessionLocal() as session:
            record = session.get(model, record_id)
            if record:
                session.delete(record)
                session.commit()
                return True
            return False

    def _get_all_by_user(self, model: Type[Base], user_id: str) -> List[Base]:
        with self.SessionLocal() as session:
            stmt = select(model).where(model.user_id == user_id)
            return list(session.scalars(stmt).all())

    # Only for Nutrition, Workout, SleepData tables
    def _get_all_in_time_range(
            self,
            model: Type[Base],
            user_id: str,
            date_column_name: str,
            start_date: Any,
            end_date: Any
    ) -> List[Base]:
        """
        Generic method to fetch records for a user within a specific time range.
        """
        with self.SessionLocal() as session:
            # Dynamically get the date/time column from the model
            date_col = getattr(model, date_column_name)

            stmt = select(model).where(
                model.user_id == user_id,
                date_col >= start_date,
                date_col <= end_date
            ).order_by(date_col.asc())  # Ordering chronologically helps the LLM read the data

            return list(session.scalars(stmt).all())

    def get_user_profile_state(self, user_id: str) -> Optional[dict]:
        """
        Fetches the user and their active goals to populate the LangGraph UserProfileSchema.
        Returns a dictionary ready to be injected into the GlobalState.
        """
        user = self.get_user(user_id)
        if not user:
            return None

        with self.SessionLocal() as session:
            # Filter for 'active' to keep the LLM's context window focused on current objectives
            active_goals = session.scalars(
                select(Goal).where(Goal.user_id == user_id, Goal.status == 'active')
            ).all()

            # Manually map to strictly match the TypedDict schema
            return {
                "id": user.id,
                "name": user.name,
                "age": user.age,
                "gender": user.gender,
                "height_cm": user.height_cm,
                "weight_kg": user.weight_kg,
                "goals": [
                    {
                        "goal_type": g.goal_type,
                        "description": g.description,
                        "target_date": g.target_date,
                        "status": g.status
                    } for g in active_goals
                ]
            }


    # --- USER CRUD ---
    def create_user(self, name: str, age: int, height_cm: float, weight_kg: float, gender: Optional[str] = None) -> User:
        user = User(name=name, age=age, height_cm=height_cm, weight_kg=weight_kg, gender=gender)
        return self._create(user)

    def get_user(self, user_id: str) -> Optional[User]:
        return self._get(User, user_id)

    def update_user(self, user_id: str, **kwargs) -> Optional[User]:
        return self._update(User, user_id, **kwargs)

    def delete_user(self, user_id: str) -> bool:
        return self._delete(User, user_id)


    # --- GOAL CRUD ---
    def create_goal(self, user_id: str, goal_type: str, description: str, target_date: Optional[datetime.date] = None) -> Goal:
        goal = Goal(user_id=user_id, goal_type=goal_type, description=description, target_date=target_date)
        return self._create(goal)

    def get_user_goals(self, user_id: str) -> List[Goal]:
        return self._get_all_by_user(Goal, user_id)

    def update_goal(self, goal_id: int, **kwargs) -> Optional[Goal]:
        return self._update(Goal, goal_id, **kwargs)

    def delete_goal(self, goal_id: int) -> bool:
        return self._delete(Goal, goal_id)


    # --- NUTRITION CRUD ---
    def create_nutrition(
        self,
        user_id: str,
        timestamp: datetime.datetime,
        food_name: str,
        calories: int,
        protein_g: float,
        carbs_g: float,
        fats_g: float,
        meal_type: Optional[str] = None
    ) -> Nutrition:
        nutrition = Nutrition(
            user_id=user_id,
            timestamp=timestamp,
            food_name=food_name,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fats_g=fats_g,
            meal_type=meal_type
        )
        return self._create(nutrition)

    def get_user_nutrition(self, user_id: str) -> List[Nutrition]:
        return self._get_all_by_user(Nutrition, user_id)

    def update_nutrition(self, nutrition_id: int, **kwargs) -> Optional[Nutrition]:
        return self._update(Nutrition, nutrition_id, **kwargs)

    def delete_nutrition(self, nutrition_id: int) -> bool:
        return self._delete(Nutrition, nutrition_id)

    def get_nutrition_in_range(self, user_id: str, start_date: datetime.datetime, end_date: datetime.datetime) -> List[Nutrition]:
        return self._get_all_in_time_range(Nutrition, user_id, 'timestamp', start_date, end_date)


    # --- WORKOUT CRUD ---
    def create_workout(self, user_id: str, timestamp: datetime.datetime, activity_type: str, duration_minutes: int, intensity: Optional[str] = None, notes: Optional[str] = None) -> Workout:
        workout = Workout(user_id=user_id, timestamp=timestamp, activity_type=activity_type, duration_minutes=duration_minutes, intensity=intensity, notes=notes)
        return self._create(workout)

    def get_user_workouts(self, user_id: str) -> List[Workout]:
        return self._get_all_by_user(Workout, user_id)

    def update_workout(self, workout_id: int, **kwargs) -> Optional[Workout]:
        return self._update(Workout, workout_id, **kwargs)

    def delete_workout(self, workout_id: int) -> bool:
        return self._delete(Workout, workout_id)

    def get_workout_in_range(self, user_id: str, start_date: datetime.datetime, end_date: datetime.datetime) -> List[
        Workout]:
        return self._get_all_in_time_range(Workout, user_id, 'timestamp', start_date, end_date)


    # --- SLEEP DATA CRUD ---
    def create_sleep_data(self, user_id: str, date: datetime.date, duration_hours: float, quality_score: Optional[int] = None, sleep_stages_json: Optional[str] = None) -> SleepData:
        sleep = SleepData(user_id=user_id, date=date, duration_hours=duration_hours, quality_score=quality_score, sleep_stages_json=sleep_stages_json)
        return self._create(sleep)

    def get_user_sleep_data(self, user_id: str) -> List[SleepData]:
        return self._get_all_by_user(SleepData, user_id)

    def update_sleep_data(self, sleep_id: int, **kwargs) -> Optional[SleepData]:
        return self._update(SleepData, sleep_id, **kwargs)

    def delete_sleep_data(self, sleep_id: int) -> bool:
        return self._delete(SleepData, sleep_id)

    def get_sleep_data_in_range(self, user_id: str, start_date: datetime.date, end_date: datetime.date) -> List[
        SleepData]:
        return self._get_all_in_time_range(SleepData, user_id, 'date', start_date, end_date)