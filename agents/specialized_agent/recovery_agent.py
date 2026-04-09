from agents.specialized_agent.base_specialized_agent import BaseSpecializedAgent

from pydantic import BaseModel, Field
from typing import List, Optional
import datetime


class RecoveryRecord(BaseModel):
    date: datetime.date = Field(
        description="The calendar date (YYYY-MM-DD) of the sleep session. Use the date the user woke up."
    )
    duration_hours: float = Field(
        description="Total sleep duration in hours as a decimal. e.g., 7.5 for 7 hours 30 minutes. Must be between 0 and 24."
    )
    quality_score: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="A 0–100 sleep quality score sourced from a wearable device. Null if no wearable data was provided."
    )
    sleep_stages_json: Optional[str] = Field(
        None,
        description="A JSON string breaking down sleep stages. e.g., '{\"deep\": 1.5, \"light\": 3.0, \"rem\": 2.0, \"awake\": 0.5}'. The sum of all stages should equal duration_hours. Null if not provided."
    )

class TaskResultModel(BaseModel):
    result: str
    proposed_db_records: List[RecoveryRecord]

class SelfEvaluationModel(BaseModel):
    is_approved: bool
    feedback_to_agent: str  # Empty if approved, detailed instructions if rejected
    result: Optional[TaskResultModel]  # Null if rejected, populated if approved


class RecoveryAgent(BaseSpecializedAgent):
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
            agent_type="recovery",
            evaluation_model=SelfEvaluationModel,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            openai_api_key=openai_api_key
        )