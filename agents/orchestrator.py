from core.state import GlobalState, AgentState, AgentName
from agents.base_agent.base_agent import BaseAgent

from langchain.messages import SystemMessage, AIMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import List, Literal
from textwrap import dedent
import json


class TaskModel(BaseModel):
    agent: AgentName
    task_description: str
    task_type: Literal["informational", "data_logging", "both"]

class ClarificationOption(BaseModel):
    id: str
    label: str

class ClarificationQuestion(BaseModel):
    id: str
    question: str
    options: List[ClarificationOption]

class PlansModel(BaseModel):
    thought_process: str
    clarification_questions: List[ClarificationQuestion] = Field(default_factory=list)
    tasks: List[TaskModel]


class Orchestrator(BaseAgent):
    def __init__(
            self,
            model: str = 'gpt-5-mini',
            temperature: float = 0.7,
            max_tokens: int = None,
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
        self.instruction_prompt = self._load_prompts("utils/prompts/orchestrator")


    def generate_plan(self, state: GlobalState):
        structured_llm = self.llm.with_structured_output(PlansModel)

        system_message = self._build_system_message("You are the Orchestrator Agent for an industry-level personal health and lifestyle system. Your mission is to act as a premier health assistant, helping the user reach their specific goals through data-driven analysis of their lifestyle. Analyze the conversation history and user profile, then follow the planning instructions at the end of this prompt.")

        context_messages = state.get("global_messages", [])[-5:]
        internal_history = state.get("orchestrator_messages", [])

        # If clarification happened, _clarification injects a single HumanMessage with the
        # answers into orchestrator_messages. Embed it directly into the instruction template
        # so the LLM reads it as part of its task brief rather than a buried prior message.
        clarification_msg = next((m for m in internal_history if isinstance(m, HumanMessage)), None)
        clarification_answers = clarification_msg.content if clarification_msg else ""

        instruction_message = HumanMessage(self.instruction_prompt["planning"].render(
            user_profile_json=json.dumps(state["user_profile"], indent=2, default=str),
            user_query=state["user_query"],
            clarification_answers=clarification_answers
        ))

        messages = [system_message] + context_messages + [instruction_message]
        plan: PlansModel = structured_llm.invoke(messages)

        if plan.clarification_questions:
            # Signal the graph to pause via the dedicated clarification node.
            # Answers will be injected into orchestrator_messages before re-planning.
            return {
                "pending_clarification": [q.model_dump() for q in plan.clarification_questions],
                "total_llm_calls": 1,
            }

        if not plan.tasks:
            return {
                "pending_clarification": [],
                "plans": {},
                "total_llm_calls": 1
            }

        # Pydantic model to readable string
        content_lines = [f"### Thought Process\n{plan.thought_process}\n", "### Generated Plan"]
        # content_lines = ["### Generated Plan"]
        for index, task in enumerate(plan.tasks, 1):
            content_lines.append(f"{index}. **{task.agent.value}**: {task.task_description}")
        ai_message = AIMessage(content="\n".join(content_lines), name="Orchestrator")

        # Conditional Edges to specialized agents
        return {
            "orchestrator_messages": [ai_message],
            "plans": {
                task.agent: {
                    "description": task.task_description,
                    "task_type": task.task_type,
                    "status": "pending",
                    "final_result": "",
                    "proposed_db_records": [],
                }
                for task in plan.tasks
            },
            "total_llm_calls": 1,
        }

    def collect_agent_results(self, state: GlobalState):
        """
        Runs AFTER all specialized agents finish their self-evaluation loops.
        It extracts their final answers and appends them as individual AIMessages
        with the agent's name attached to the history.
        """
        new_messages = []

        for agent_name, task_data in state.get("plans", {}).items():
            if task_data.get("status") == "completed":
                db_records = task_data.get("proposed_db_records", [])
                db_dicts = [record.model_dump() for record in db_records]

                result_content = dedent(
                    f"""Task: {task_data['description']}
                    Result: {task_data['final_result']}
                    
                    Extracted Data (Saved to DB):
                    ```json
                    {json.dumps(db_dicts, indent=2, default=str)}
                    ```
                    """
                )

                # Create an AIMessage explicitly named after the specialized agent
                agent_msg = AIMessage(
                    content=result_content,
                    name=agent_name.value
                )
                new_messages.append(agent_msg)

        return {
            "orchestrator_messages": new_messages,
            # Clear the plans so the orchestrator starts fresh on the next planning cycle
            "plans": {}
        }

    def synthesis_answer(self, state: GlobalState):
        synthesis_prompt_template = self.instruction_prompt["synthesis_answer"]
        synthesis_system_prompt_content = synthesis_prompt_template.render(
            user_profile_json=json.dumps(state["user_profile"], indent=2, default=str),
            # The user_query is now provided as the last HumanMessage in the conversation history.
        )
        synthesis_system_message = self._build_system_message(synthesis_system_prompt_content)

        context_messages = state.get("global_messages", [])
        agent_reports = state.get("orchestrator_messages", [])
        user_message = HumanMessage(content=state["user_query"])
        messages = [synthesis_system_message] + context_messages + agent_reports + [user_message]

        final_answer = self.llm.invoke(messages)

        # We append the user's query and the Orchestrator's final answer to the global chat history.
        # We also clear the orchestrator_messages so the internal scratchpad is clean for the next user query.
        return {
            "global_messages": [user_message, final_answer],
            "orchestrator_messages": [],  # Reset internal history for the next turn
            "total_llm_calls": 1
        }
