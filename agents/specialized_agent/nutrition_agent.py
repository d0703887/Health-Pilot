from agents.specialized_agent.base_specialized_agent import BaseSpecializedAgent

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class NutritionRecord(BaseModel):
    timestamp: datetime = Field(
        description="ISO 8601 datetime of when the food was consumed. Default to the current time if not specified."
    )
    food_name: str = Field(
        description="Name of the specific food or drink item consumed. e.g., 'Chicken Breast', 'Protein Shake'."
    )
    calories: int = Field(
        description="Total caloric value of the item in kcal. Must be a positive integer."
    )
    protein_g: float = Field(
        description="Total protein content in grams."
    )
    carbs_g: float = Field(
        description="Total carbohydrate content in grams."
    )
    fats_g: float = Field(
        description="Total fat content in grams. Cross-check: (protein_g * 4) + (carbs_g * 4) + (fats_g * 9) should approximately equal calories (within 10%)."
    )
    meal_type: Optional[str] = Field(
        None,
        description="The meal context. Must be one of: 'Breakfast', 'Lunch', 'Dinner', 'Snack'. Null if not determinable."
    )

class TaskResultModel(BaseModel):
    result: str
    proposed_db_records: List[NutritionRecord]

class SelfEvaluationModel(BaseModel):
    is_approved: bool
    feedback_to_agent: str  # Empty if approved, detailed instructions if rejected
    result: Optional[TaskResultModel]  # Null if rejected, populated if approved


class NutritionAgent(BaseSpecializedAgent):
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
            agent_type="nutrition",
            evaluation_model=SelfEvaluationModel,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            openai_api_key=openai_api_key
        )

