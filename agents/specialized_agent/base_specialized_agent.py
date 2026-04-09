from agents.base_agent.base_agent import BaseAgent
from core.state import AgentState

import json
import copy
from typing import Type, Optional
from langchain.messages import SystemMessage, AIMessage
from pydantic import BaseModel


class BaseSpecializedAgent(BaseAgent):
    def __init__(
            self,
            agent_type: str,  # e.g., 'exercise', 'nutrition', 'recovery'
            evaluation_model: Type[BaseModel],
            tools: list,
            model: str = 'gpt-5-mini',
            temperature: float = 0.7,
            max_tokens: Optional[int] = None,
            streaming: bool = False,
            openai_api_key: str = ""
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            openai_api_key=openai_api_key
        )

        # Dynamically load prompts based on the agent type string
        self.instruction_prompt = self._load_prompts(f"utils/prompts/{agent_type}_agent")

        # Store the specific Pydantic model for this agent's structured output
        self.evaluation_model = evaluation_model

        # Bind tools once at construction time so do_task can reuse this in its loop.
        # bind_tools() tells the LLM which tools exist and what their schemas are.
        # Without this, the LLM cannot produce tool_calls in its responses.
        self.llm_with_tools = self.llm.bind_tools(tools)

    def do_task(self, state: AgentState):
        # Normalize: checkpointer deserializes AgentName enum as a plain str on resume
        agent_name = state["agent_name"]
        if hasattr(agent_name, "value"):
            agent_name = agent_name.value
        history_messages = state.get("working_messages", [])

        if not history_messages:
            history_messages = [self._build_system_message(self.instruction_prompt["do_task"].render(
                user_profile_json=json.dumps(state["user_profile"], indent=2, default=str),
                task_description=state["plans"][agent_name]["description"],
                task_type=state["plans"][agent_name]["task_type"],
            ))]

        response = self.llm_with_tools.invoke(history_messages)
        response.name = agent_name

        return {
            "working_messages": history_messages + [response] if not state.get("working_messages") else [response],
            "total_llm_calls": 1
        }

    def self_evaluation(self, state: AgentState):
        # Use the evaluation_model passed during initialization
        structured_llm = self.llm.with_structured_output(self.evaluation_model)
        agent_name = state["agent_name"]
        # Normalize: checkpointer deserializes AgentName enum as a plain str on resume
        if hasattr(agent_name, "value"):
            agent_name = agent_name.value
        agent_response = state["working_messages"][-1].content

        system_prompt = self.instruction_prompt["self_evaluation"].render(
            task_description=state["plans"][agent_name]["description"],
            task_type=state["plans"][agent_name]["task_type"],
            user_profile_json=json.dumps(state["user_profile"], indent=2, default=str),
            agent_response=agent_response
        )

        evaluation = structured_llm.invoke([self._build_system_message(system_prompt)])
        updated_task = copy.deepcopy(state["plans"][agent_name])

        if evaluation.is_approved:
            updated_task["final_result"] = evaluation.result.result
            updated_task["proposed_db_records"] = evaluation.result.proposed_db_records
            updated_task["status"] = "completed"

            return {
                "working_messages": [],
                "plans": {agent_name: updated_task},
                "total_llm_calls": 1
            }
        else:
            evaluation_message = AIMessage(content=evaluation.feedback_to_agent, name="Reviewer")
            return {
                "working_messages": [evaluation_message],
                "total_llm_calls": 1
            }
