from langchain.messages import AnyMessage
from typing_extensions import TypedDict, Annotated
from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel
import datetime
import operator
from enum import Enum


class AgentName(str, Enum):
    ORCHESTRATOR = "orchestrator"
    NUTRITION = "nutrition_agent"
    EXERCISE = "exercise_agent"
    RECOVERY = "recovery_agent"


class GoalSchema(TypedDict):
    goal_type: str
    description: str
    target_date: Optional[datetime.date]
    status: Literal["active", "completed", "abandoned"]


class UserProfileSchema(TypedDict):
    id: str
    name: str
    age: int
    gender: Optional[str]
    height_cm: float
    weight_kg: float
    goals: List[GoalSchema]


class Task(TypedDict):
    description: str
    task_type: Literal["informational", "data_logging", "both"]
    status: Literal["pending", "completed", "failed"]
    final_result: str
    proposed_db_records: List[BaseModel]


def clearable_message_add(left: List[AnyMessage], right: List[AnyMessage]) -> List[AnyMessage]:
    if not right:
        return []
    return left + right

def merge_plans(left: Dict[AgentName, Task], right: Dict[AgentName, Task]) -> Dict[AgentName, Task]:
    if not right:
        return {}
    merged = left.copy()
    for key, task in right.items():
        if key not in merged or task.get("status") == "completed":
            merged[key] = task
    return merged

def keep_last(a, b):
    """Reducer for read-only fields shared across parallel subgraphs. All agents carry
    identical copies, so taking the latest write is always safe."""
    return b


class GlobalState(TypedDict):
    global_messages: Annotated[List[AnyMessage], operator.add]
    orchestrator_messages: Annotated[List[AnyMessage], clearable_message_add]
    plans: Annotated[Dict[AgentName, Task], merge_plans]
    pending_clarification: Annotated[List[Any], clearable_message_add]
    total_llm_calls: Annotated[int, operator.add]

    # Read-only — reducers required to allow parallel subgraph writes
    user_profile: Annotated[UserProfileSchema, keep_last]
    user_query: Annotated[str, keep_last]
    user_id: Annotated[str, keep_last]


class AgentState(TypedDict):
    # Private to specialized agents
    agent_name: str
    working_messages: Annotated[List[AnyMessage], clearable_message_add]

    # Shared
    global_messages: Annotated[List[AnyMessage], operator.add]
    user_profile: Annotated[UserProfileSchema, keep_last]
    user_id: Annotated[str, keep_last]
    plans: Annotated[Dict[AgentName, Task], merge_plans]
    total_llm_calls: Annotated[int, operator.add]
