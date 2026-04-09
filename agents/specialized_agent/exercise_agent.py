from agents.specialized_agent.base_specialized_agent import BaseSpecializedAgent

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class WorkoutRecord(BaseModel):
    timestamp: datetime = Field(
        description="ISO 8601 datetime of when the workout took place. Default to the current time if not specified."
    )
    activity_type: str = Field(
        description="The type of physical activity performed. e.g., 'Weightlifting', 'Running', 'Cycling', 'HIIT'."
    )
    duration_minutes: int = Field(
        description="Total duration of the workout in whole minutes. Must be a positive integer."
    )
    intensity: Optional[str] = Field(
        None,
        description="Subjective or derived intensity level. Must be exactly one of: 'Low', 'Moderate', 'High'. Null if not determinable."
    )
    notes: Optional[str] = Field(
        None,
        description="Any additional context about the workout. e.g., sets/reps, perceived exertion, injuries. Null if not applicable."
    )

class TaskResultModel(BaseModel):
    result: str
    proposed_db_records: List[WorkoutRecord]

class SelfEvaluationModel(BaseModel):
    is_approved: bool
    feedback_to_agent: str  # Empty if approved, detailed instructions if rejected
    result: Optional[TaskResultModel]  # Null if rejected, populated if approved


class ExerciseAgent(BaseSpecializedAgent):
    def __init__(
            self,
            tools: list,
            model: str = 'gpt-5-mini',
            temperature: float = 0.7,
            max_tokens: int = None,
            streaming: bool = False,
            openai_api_key: str = ""
    ):
        super().__init__(
            agent_type="exercise",
            evaluation_model=SelfEvaluationModel,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            openai_api_key=openai_api_key
        )