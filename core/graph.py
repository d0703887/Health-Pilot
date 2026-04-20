import uuid
import time
import warnings
import logging
from concurrent.futures import ThreadPoolExecutor

import os
from core.config import settings
os.environ["LANGCHAIN_TRACING"] = "true"
os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY

logger = logging.getLogger(__name__)
warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
    module="pydantic"
)

from agents import Orchestrator, NutritionAgent, ExerciseAgent, RecoveryAgent
from tools import UnifiedMemoryManager, WebSearchTool, MemoryExtractor
from core.state import GlobalState, AgentState, AgentName

import redis
from sqlalchemy import create_engine
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from typing import Dict, Any
from pydantic import BaseModel, Field
import json

from langchain.tools import tool, ToolRuntime
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt, Command
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langchain.messages import HumanMessage, AIMessage


# TODO: Log and update user goals

AGENT2TABLE = {
    AgentName.NUTRITION: "nutrition",
    AgentName.EXERCISE: "workout",
    AgentName.RECOVERY: "sleep"
}


class GetRecentHealthSnapshotSchema(BaseModel):
    days: int = Field(
        default=7,
        description="The number of recent days to include in the health snapshot."
    )

class WebSearchSchema(BaseModel):
    query: str = Field(
        ...,
        description="The search query to execute."
    )
    search_depth: str = Field(
        default='basic',
        description="The depth of the web search. 'basic' or 'advanced'."
    )
    max_results: int = Field(
        default=5,
        description="The maximum number of search results to return."
    )


class Graph:
    def __init__(
            self,
            redis_host: str = "localhost",
            redis_port: int = 6379,
            redis_db: int = 0,
            ttl_hours: int = 24,
            sql_db_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres",
            openai_api_key: str = "",
            openai_model_name: str = "text-embedding-3-small",
            chroma_host: str = "localhost",
            chroma_port: int = 8000,
            tavily_api_key: str = ""
    ):
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True
        )

        self.sql_engine = create_engine(
            sql_db_url,
            echo=False,
            pool_size=10,
            max_overflow=10,
            pool_recycle=1800
        )

        self.openai_ef = OpenAIEmbeddingFunction(
            api_key=openai_api_key,
            model_name=openai_model_name
        )
        self.chroma_client = chromadb.HttpClient(
            host=chroma_host,
            port=chroma_port,
        )

        pg_conn_string = sql_db_url.replace("postgresql+psycopg://", "postgresql://")
        self._pg_conn = psycopg.connect(pg_conn_string, autocommit=True)
        self.checkpointer = PostgresSaver(self._pg_conn)
        self.checkpointer.setup()

        self.memory_manager = UnifiedMemoryManager(
            self.redis_client,
            ttl_hours,
            self.sql_engine,
            self.openai_ef,
            self.chroma_client
        )
        self.websearch = WebSearchTool(tavily_api_key)
        self.memory_extractor = MemoryExtractor(openai_api_key=openai_api_key)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mem_extract")

        # Build the tool list once. Agents bind their LLM to these tools at
        # construction time; the ToolNode uses the same list to execute calls.
        self._tools = self.tools()

        self.orchestrator = Orchestrator(openai_api_key=openai_api_key)
        self.nutrition_agent = NutritionAgent(tools=self._tools, openai_api_key=openai_api_key)
        self.exercise_agent = ExerciseAgent(tools=self._tools, openai_api_key=openai_api_key)
        self.recovery_agent = RecoveryAgent(tools=self._tools, openai_api_key=openai_api_key)

        self.graph = self._build_graph()

    # --- Nodes ---

    # -- LLM Nodes --
    def _planning(self, state: GlobalState) -> GlobalState:
        return self.orchestrator.generate_plan(state)

    def _nutrition_agent_do_task(self, state: AgentState) -> AgentState:
        return self.nutrition_agent.do_task(state)

    def _nutrition_agent_self_evaluation(self, state: AgentState) -> AgentState:
        return self.nutrition_agent.self_evaluation(state)

    def _exercise_agent_do_task(self, state: AgentState) -> AgentState:
        return self.exercise_agent.do_task(state)

    def _exercise_agent_self_evaluation(self, state: AgentState) -> AgentState:
        return self.exercise_agent.self_evaluation(state)

    def _recovery_agent_do_task(self, state: AgentState) -> AgentState:
        return self.recovery_agent.do_task(state)

    def _recovery_agent_self_evaluation(self, state: AgentState) -> AgentState:
        return self.recovery_agent.self_evaluation(state)

    def _orchestrator_collect_agent_results(self, state: GlobalState) -> GlobalState:
        return self.orchestrator.collect_agent_results(state)

    def _orchestrator_synthesis_answer(self, state: GlobalState) -> GlobalState:
        return self.orchestrator.synthesis_answer(state)

    # -- Tool Nodes --
    def _get_recent_health_snapshot(self, runtime: ToolRuntime, days: int = 7) -> Dict[str, Any]:
        return self.memory_manager.get_recent_health_snapshot(user_id=runtime.state["user_id"], days=days)

    def _web_search(self, query: str, search_depth: str = 'basic', max_results: int = 5):
        return self.websearch.search(query=query, search_depth=search_depth, max_results=max_results)

    def tools(self):

        @tool(args_schema=GetRecentHealthSnapshotSchema)
        def get_recent_health_snapshot(runtime: ToolRuntime, days: int = 7):
            """Retrieve the user's logged health snapshot"""
            return self._get_recent_health_snapshot(runtime, days)

        @tool(args_schema=WebSearchSchema)
        def web_search(query: str, search_depth: str = 'basic', max_results: int = 5):
            """Executes a web search."""
            return self._web_search(query, search_depth, max_results)

        return [get_recent_health_snapshot, web_search]

    # -- Other --
    def _log_database(self, state: AgentState):
        agent_name = state["agent_name"]
        # Normalize: checkpointer deserializes AgentName enum as a plain str on resume
        if hasattr(agent_name, "value"):
            agent_name = agent_name.value
        for db_records in state["plans"][agent_name]["proposed_db_records"]:
            record_dict = db_records.model_dump()
            self.memory_manager.log_entry(
                user_id=state["user_id"],
                entry_type=AGENT2TABLE[AgentName(agent_name)],
                **record_dict
            )

        return {"working_messages": []}

    def _clarification(self, state: GlobalState):
        questions = state["pending_clarification"]
        answers = interrupt({"questions": questions})

        # answers = {question_text: selected_option_id}
        # LangGraph strips the interrupt ID; interrupt() returns the inner dict directly.
        inner_answers: dict = answers if answers else {}

        lines = ["The user was asked for clarification. Full context and selections:"]
        for question in questions:
            q_text = question.question if hasattr(question, "question") else question["question"]
            q_options = question.options if hasattr(question, "options") else question["options"]

            selected_id = inner_answers.get(q_text, "")

            selected_label = selected_id  # fallback for free-text entries
            option_lines = []
            for opt in q_options:
                opt_id = opt.id if hasattr(opt, "id") else opt["id"]
                opt_label = opt.label if hasattr(opt, "label") else opt["label"]
                marker = " ← selected" if opt_id == selected_id else ""
                option_lines.append(f"    [{opt_id}] {opt_label}{marker}")
                if opt_id == selected_id:
                    selected_label = opt_label

            lines.append(f"\nQ: {q_text}")
            lines.append("Options:\n" + "\n".join(option_lines))
            lines.append(f'User selected: "{selected_label}"')

        answer_message = HumanMessage(content="\n".join(lines))
        return {
            "pending_clarification": [],
            "orchestrator_messages": [answer_message],
        }

    # --- Routing Logic ---
    # -- Orchestrator --
    def route_from_planning(self, state: GlobalState):
        if state.get("pending_clarification"):
            return "clarification"
        if state["plans"]:
            return list(map(lambda x: x.value, state["plans"].keys()))
        return "synthesis_answer"

    # -- Specialized Agents --
    def route_from_do_task(self, state: AgentState):
        last_message = state["working_messages"][-1]
        if last_message.tool_calls:
            return "tool_node"
        else:
            return "self_evaluation"

    def route_from_self_evaluation(self, state: AgentState):
        agent_name = state["agent_name"]
        if hasattr(agent_name, "value"):
            agent_name = agent_name.value
        if state["plans"][agent_name]["status"] == "completed":
            return "log_database"
        else:
            return "do_task"

    def _build_graph(self):
        tool_node = ToolNode(self._tools, messages_key="working_messages")
        nutrition_subgraph = self._build_nutrition_subgraph(tool_node)
        exercise_subgraph = self._build_exercise_subgraph(tool_node)
        recovery_subgraph = self._build_recovery_subgraph(tool_node)

        orchestrator_workflow = StateGraph(GlobalState)
        orchestrator_workflow.add_node("orchestrator_planning", self._planning)
        orchestrator_workflow.add_node("clarification", self._clarification)
        orchestrator_workflow.add_node("nutrition_agent", nutrition_subgraph)
        orchestrator_workflow.add_node("exercise_agent", exercise_subgraph)
        orchestrator_workflow.add_node("recovery_agent", recovery_subgraph)
        orchestrator_workflow.add_node("collect_agent_results", self._orchestrator_collect_agent_results)
        orchestrator_workflow.add_node("synthesis_answer", self._orchestrator_synthesis_answer)
        # path_map is provided solely for graph visualization — LangGraph cannot
        # statically infer all destinations when the router returns a list or string.
        orchestrator_workflow.add_conditional_edges(
            "orchestrator_planning",
            self.route_from_planning,
            {
                "clarification": "clarification",
                "nutrition_agent": "nutrition_agent",
                "exercise_agent": "exercise_agent",
                "recovery_agent": "recovery_agent",
                "synthesis_answer": "synthesis_answer",
            }
        )
        orchestrator_workflow.add_edge("clarification", "orchestrator_planning")
        orchestrator_workflow.add_edge("nutrition_agent", "collect_agent_results")
        orchestrator_workflow.add_edge("exercise_agent", "collect_agent_results")
        orchestrator_workflow.add_edge("recovery_agent", "collect_agent_results")
        orchestrator_workflow.add_edge("collect_agent_results", "synthesis_answer")
        orchestrator_workflow.add_edge("synthesis_answer", END)
        orchestrator_workflow.set_entry_point("orchestrator_planning")

        return orchestrator_workflow.compile(checkpointer=self.checkpointer)

    def _build_nutrition_subgraph(self, tool_node):
        def set_agent_name(state: AgentState):
            return {"agent_name": AgentName.NUTRITION}

        # Nodes
        nutrition_workflow = StateGraph(AgentState)
        nutrition_workflow.add_node("set_agent_name", set_agent_name)
        nutrition_workflow.add_node("do_task", self._nutrition_agent_do_task)
        nutrition_workflow.add_node("tool_node", tool_node)
        nutrition_workflow.add_node("self_evaluation", self._nutrition_agent_self_evaluation)
        nutrition_workflow.add_node("log_database", self._log_database)

        # Edges
        # path_map is provided solely for graph visualization — LangGraph cannot
        # statically infer all destinations when the router returns a list or string.
        nutrition_workflow.add_edge(START, "set_agent_name")
        nutrition_workflow.add_edge("set_agent_name", "do_task")
        nutrition_workflow.add_conditional_edges(
            "do_task",
            self.route_from_do_task,
            {
                "tool_node": "tool_node",
                "self_evaluation": "self_evaluation"
            }
        )
        nutrition_workflow.add_edge("tool_node", "do_task")
        nutrition_workflow.add_conditional_edges(
            "self_evaluation",
            self.route_from_self_evaluation,
            {
                "log_database": "log_database",
                "do_task": "do_task"
            }
        )
        nutrition_workflow.add_edge("log_database", END)

        nutrition_subgraph = nutrition_workflow.compile()
        return nutrition_subgraph

    def _build_exercise_subgraph(self, tool_node):
        def set_agent_name(state: AgentState):
            return {"agent_name": AgentName.EXERCISE}

        # Nodes
        exercise_workflow = StateGraph(AgentState)
        exercise_workflow.add_node("set_agent_name", set_agent_name)
        exercise_workflow.add_node("do_task", self._exercise_agent_do_task)
        exercise_workflow.add_node("tool_node", tool_node)
        exercise_workflow.add_node("self_evaluation", self._exercise_agent_self_evaluation)
        exercise_workflow.add_node("log_database", self._log_database)

        # Edges
        # path_map is provided solely for graph visualization — LangGraph cannot
        # statically infer all destinations when the router returns a list or string.
        exercise_workflow.add_edge(START, "set_agent_name")
        exercise_workflow.add_edge("set_agent_name", "do_task")
        exercise_workflow.add_conditional_edges(
            "do_task",
            self.route_from_do_task,
            {
                "tool_node": "tool_node",
                "self_evaluation": "self_evaluation"
            }
        )
        exercise_workflow.add_edge("tool_node", "do_task")
        exercise_workflow.add_conditional_edges(
            "self_evaluation",
            self.route_from_self_evaluation,
            {
                "log_database": "log_database",
                "do_task": "do_task"
            }
        )
        exercise_workflow.add_edge("log_database", END)

        exercise_subgraph = exercise_workflow.compile()
        return exercise_subgraph

    def _build_recovery_subgraph(self, tool_node):
        def set_agent_name(state: AgentState):
            return {"agent_name": AgentName.RECOVERY}

        # Nodes
        recovery_workflow = StateGraph(AgentState)
        recovery_workflow.add_node("set_agent_name", set_agent_name)
        recovery_workflow.add_node("do_task", self._recovery_agent_do_task)
        recovery_workflow.add_node("tool_node", tool_node)
        recovery_workflow.add_node("self_evaluation", self._recovery_agent_self_evaluation)
        recovery_workflow.add_node("log_database", self._log_database)

        # Edges
        # path_map is provided solely for graph visualization — LangGraph cannot
        # statically infer all destinations when the router returns a list or string.
        recovery_workflow.add_edge(START, "set_agent_name")
        recovery_workflow.add_edge("set_agent_name", "do_task")
        recovery_workflow.add_conditional_edges(
            "do_task",
            self.route_from_do_task,
            {
                "tool_node": "tool_node",
                "self_evaluation": "self_evaluation"
            }
        )
        recovery_workflow.add_edge("tool_node", "do_task")
        recovery_workflow.add_conditional_edges(
            "self_evaluation",
            self.route_from_self_evaluation,
            {
                "log_database": "log_database",
                "do_task": "do_task"
            }
        )
        recovery_workflow.add_edge("log_database", END)

        recovery_subgraph = recovery_workflow.compile()
        return recovery_subgraph

    def _build_initial_state(self, user_id: str, user_query: str) -> GlobalState:
        user_profile = self.memory_manager.get_user_profile(user_id)
        if user_profile is None:
            raise ValueError(f"User '{user_id}' not found.")

        history = self.memory_manager.get_conversation_history(user_id)
        global_messages = []
        for msg in history:
            if msg["role"] == "human":
                global_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "ai":
                global_messages.append(AIMessage(content=msg["content"]))

        return {
            "user_id": user_id,
            "user_query": user_query,
            "user_profile": user_profile,
            "global_messages": global_messages,
            "orchestrator_messages": [],
            "plans": {},
            "pending_clarification": [],
            "total_llm_calls": 0,
        }

    EXTRACTION_THRESHOLD = 10  # messages since last extraction

    def _extract_memories(self, user_id: str, messages: list) -> None:
        """Runs in a background thread. Extracts insights and writes to ChromaDB."""
        logger.debug("Memory extraction started | user=%s | messages=%d", user_id, len(messages))
        try:
            self.memory_extractor.extract_and_store(user_id, messages, self.memory_manager)
            logger.debug("Memory extraction complete | user=%s", user_id)
        except Exception:
            logger.exception("Memory extraction failed | user=%s", user_id)

    def _trigger_extraction_if_ready(self, user_id: str) -> None:
        """Checks the cursor and submits extraction to the thread pool if threshold is met."""
        messages, last_score = self.memory_manager.get_messages_since_cursor(user_id, self.EXTRACTION_THRESHOLD)
        if messages:
            self.memory_manager.advance_memory_cursor(user_id, last_score)
            self._executor.submit(self._extract_memories, user_id, messages)

    def run(self, user_id: str, user_query: str) -> dict:
        thread_id = str(uuid.uuid4())  # fresh per invocation — no checkpoint conflict
        config = {"configurable": {"thread_id": thread_id}}

        logger.info("Run started | user=%s | thread=%s | query=%.80s", user_id, thread_id, user_query)
        initial_state = self._build_initial_state(user_id, user_query)

        final_state = self.graph.invoke(initial_state, config=config)

        if final_state.get("__interrupt__"):
            interrupts = [{"id": intr.id, **intr.value} for intr in final_state["__interrupt__"]]
            logger.info("Run paused for clarification | user=%s | thread=%s | interrupts=%d",
                        user_id, thread_id, len(interrupts))
            return {"type": "clarification", "thread_id": thread_id, "interrupts": interrupts}

        # Persist the new turn to Redis after the graph completes.
        # Pass explicit scores so human always sorts before AI even when time.time()
        # returns the same float for both back-to-back calls (e.g. on Windows ~15ms clock).
        t = time.time()
        self.memory_manager.add_to_conversation_history(user_id, role="human", content=user_query, score=t)
        self.memory_manager.add_to_conversation_history(user_id, role="ai", content=final_state["global_messages"][-1].content, score=t + 0.001)
        self._trigger_extraction_if_ready(user_id)

        logger.info("Run complete | user=%s | thread=%s | llm_calls=%d",
                    user_id, thread_id, final_state.get("total_llm_calls", 0))
        return {"type": "answer", "content": final_state["global_messages"][-1].content}

    def resume(self, thread_id: str, answers: dict[str, str]) -> dict:
        """Resume a paused graph. answers maps each interrupt id to the user's response."""
        logger.info("Resume | thread=%s", thread_id)
        config = {"configurable": {"thread_id": thread_id}}
        final_state = self.graph.invoke(Command(resume=answers), config=config)

        if final_state.get("__interrupt__"):
            interrupts = [{"id": intr.id, **intr.value} for intr in final_state["__interrupt__"]]
            logger.info("Resume paused again for clarification | thread=%s | interrupts=%d",
                        thread_id, len(interrupts))
            return {"type": "clarification", "thread_id": thread_id, "interrupts": interrupts}

        user_id = final_state["user_id"]
        user_query = final_state["user_query"]
        t = time.time()
        self.memory_manager.add_to_conversation_history(user_id, role="human", content=user_query, score=t)
        self.memory_manager.add_to_conversation_history(user_id, role="ai", content=final_state["global_messages"][-1].content, score=t + 0.001)
        self._trigger_extraction_if_ready(user_id)

        logger.info("Resume complete | user=%s | thread=%s | llm_calls=%d",
                    user_id, thread_id, final_state.get("total_llm_calls", 0))
        return {"type": "answer", "content": final_state["global_messages"][-1].content}

    def close(self):
        """Closes underlying connections managed by the Graph object."""
        logger.info("Closing Graph resources...")
        self._executor.shutdown(wait=False)
        if self.sql_engine:
            self.sql_engine.dispose()
        if self.redis_client:
            self.redis_client.close()
        if self._pg_conn:
            self._pg_conn.close()
        if self.checkpointer:
            self.checkpointer.conn.close()


if __name__ == '__main__':
    import os
    from core.config import settings
    from memory.sql.sql_manager import SQLManager
    from sqlalchemy import create_engine
    from datetime import date, datetime, timedelta, timezone

    os.environ["LANGCHAIN_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY

    def seed_historical_data(sql: SQLManager, user_id: str) -> None:
        """Seeds 7 days of realistic nutrition, workout, and sleep data for a muscle-gain user."""
        today = date.today()

        # Each entry: (days_ago, meal_type, food_name, cal, pro, carb, fat)
        nutrition_entries = [
            # Day 7 ago
            (7, "Breakfast", "Oatmeal with whey protein scoop", 380, 30, 52, 7),
            (7, "Lunch",     "Chicken breast 200g + rice 1 cup", 535, 66, 45, 8),
            (7, "Dinner",    "Salmon 150g + sweet potato", 480, 40, 38, 14),
            # Day 6
            (6, "Breakfast", "Scrambled eggs (3) + whole wheat toast", 420, 28, 36, 18),
            (6, "Lunch",     "Ground beef stir-fry with vegetables", 550, 45, 30, 22),
            (6, "Dinner",    "Greek yogurt + banana + almonds", 410, 22, 52, 14),
            # Day 5
            (5, "Breakfast", "Protein shake + oatmeal", 350, 35, 40, 6),
            (5, "Lunch",     "Turkey sandwich on whole grain", 490, 38, 48, 12),
            (5, "Dinner",    "Tuna pasta 300g", 560, 42, 62, 9),
            # Day 4
            (4, "Breakfast", "Eggs 3 + avocado toast", 480, 26, 34, 26),
            (4, "Lunch",     "Chicken wrap + salad", 520, 44, 42, 14),
            (4, "Dinner",    "Beef mince bolognese + pasta", 640, 48, 58, 18),
            # Day 3
            (3, "Breakfast", "Oatmeal with banana and peanut butter", 430, 14, 62, 14),
            (3, "Lunch",     "Grilled chicken 180g + quinoa", 500, 58, 40, 10),
            (3, "Dinner",    "Pork tenderloin + roasted potatoes", 520, 46, 44, 12),
            # Day 2
            (2, "Breakfast", "Protein pancakes (whey based)", 390, 32, 44, 8),
            (2, "Lunch",     "Tuna salad + brown rice", 470, 40, 48, 10),
            (2, "Dinner",    "Chicken thighs + broccoli + rice", 580, 52, 46, 14),
            # Day 1
            (1, "Breakfast", "Greek yogurt 200g + granola + berries", 370, 20, 50, 8),
            (1, "Lunch",     "Egg fried rice with chicken", 540, 40, 56, 14),
            (1, "Dinner",    "Steak 200g + mashed potato", 620, 54, 42, 20),
        ]

        for days_ago, meal_type, food_name, cal, pro, carb, fat in nutrition_entries:
            ts = datetime(today.year, today.month, today.day, 12, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)
            sql.create_nutrition(user_id, ts, food_name, cal, pro, carb, fat, meal_type)

        # Each entry: (days_ago, activity_type, duration_minutes, intensity, notes)
        workout_entries = [
            (7, "Weightlifting", 60, "High",     "Upper body — bench press, OHP, rows. 4 sets each."),
            (6, "Running",       35, "Moderate", "5km easy run, zone 2 cardio."),
            (5, "Weightlifting", 65, "High",     "Lower body — squat, deadlift, leg press. PRed squat at 100kg."),
            (3, "Weightlifting", 55, "High",     "Upper body — pull focus: pull-ups, lat pulldown, face pulls."),
            (2, "Cycling",       40, "Moderate", "Stationary bike, recovery cardio."),
            (1, "Weightlifting", 70, "High",     "Full body compound session — squat, bench, deadlift."),
        ]

        for days_ago, activity, duration, intensity, notes in workout_entries:
            ts = datetime(today.year, today.month, today.day, 18, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)
            sql.create_workout(user_id, ts, activity, duration, intensity, notes)

        # Each entry: (days_ago, duration_hours, quality_score)
        sleep_entries = [
            (7, 7.5, 78),
            (6, 6.5, 62),  # poor night
            (5, 8.0, 85),
            (4, 7.0, 70),
            (3, 7.5, 80),
            (2, 6.0, 58),  # another poor night
            (1, 8.5, 88),
        ]

        for days_ago, duration, quality in sleep_entries:
            d = today - timedelta(days=days_ago)
            sql.create_sleep_data(user_id, d, duration, quality)

        print(f"Seeded 7 days of historical data for user {user_id}.")

    # --- 1. Seed a fake user ---
    engine = create_engine(settings.SQLALCHEMY_DATABASE_URI)
    sql = SQLManager(engine)

    user = sql.create_user(name="Test Dan", age=27, height_cm=178, weight_kg=75, gender="male")
    sql.create_goal(user.id, goal_type="muscle_gain", description="Gain 3kg of muscle in 12 weeks", target_date=date.today() + timedelta(weeks=12))
    seed_historical_data(sql, user.id)

    print(f"Created test user: {user.id}")

    # --- 2. Run the graph ---
    g = Graph(
      redis_host=settings.REDIS_HOST,
      redis_port=settings.REDIS_PORT,
      redis_db=settings.REDIS_DB,
      sql_db_url=settings.SQLALCHEMY_DATABASE_URI,
      openai_api_key=settings.OPENAI_API_KEY,
      chroma_host=settings.CHROMA_HOST,
      chroma_port=settings.CHROMA_PORT,
      tavily_api_key=settings.TAVILY_API_KEY,
    )

    # print(g.memory_manager.get_recent_health_snapshot(user.id, 14))
    # exit(0)
    # Visualization
    # from PIL import Image
    # import io
    #
    # # Correctly draw and save the graph visualization
    # graph_bytes = g.graph.get_graph(xray=True).draw_mermaid_png()
    # img = Image.open(io.BytesIO(graph_bytes))
    # img.save("langgraph_workflow.png")
    # print("LangGraph workflow saved to langgraph_workflow.png")


    test_cases = [
        # Case 1: No specialized agents — orchestrator answers directly from profile + history.
        # ("Case 1 - Direct synthesis", "How many calories should I eat per day to gain muscle?"),

        # # Case 2: Out of domain — should be handled gracefully by synthesis with no agent delegation.
        # ("Case 2 - Out of domain", "What do you think about the latest iPhone?"),
        #
        # # Case 3: Single agent, logging only.
        # ("Case 3 - Nutrition logging", "I just had 200g of chicken breast and a cup of rice for lunch."),
        #
        # # Case 4: Single agent, logging with missing quantity — agent should infer and state assumption.
        # ("Case 4 - Nutrition logging (vague portion)", "I had some pasta for dinner."),
        #
        # # Case 5: Single agent, logging + advice in one query.
        # ("Case 5 - Exercise logging + advice", "I just did a 45-minute weightlifting session, chest and triceps. Was that enough volume?"),
        #
        # # Case 6: Single agent, recovery logging.
        # ("Case 6 - Sleep logging", "I slept from 11 PM to 6:30 AM last night."),
        #
        # # Case 7: Multiple agents — nutrition and exercise both need to log.
        # ("Case 7 - Multi-agent logging", "I had oatmeal for breakfast and then ran for 30 minutes this morning."),
        #
        # # Case 8: Multiple agents — logging + cross-domain advice.
        # ("Case 8 - Multi-agent logging + advice", "I slept 5 hours and skipped breakfast. What should I eat and should I still train today?"),
        #
        # # Case 9: Clarification required — activity type missing, orchestrator must ask.
        # ("Case 9 - Clarification (vague exercise)", "I just finished working out."),
        #
        # # Case 10: Clarification required — sleep intent clear but no duration given.
        # ("Case 10 - Clarification (vague sleep)", "I just woke up, log my sleep."),
        #
        # --- History-aware cases (require seeded data) ---
        ("Case 11 - Weekly nutrition review", "How has my nutrition been this past week? Am I eating enough protein for muscle gain?"),
        ("Case 11-continued", "What do you mean protein is too low?")
        # ("Case 12 - Weekly training review", "Give me a summary of my training this week. Is my volume and frequency good for muscle gain?"),
        # ("Case 13 - Sleep + training cross-domain", "I've been feeling tired and my sleep has been inconsistent. Should I still train hard today?"),
        # ("Case 14 - Cross-domain weekly summary", "How has my overall week been in terms of food, training, and sleep? What should I focus on next week?"),
        # ("Case 15 - Nutrition gap advice", "My muscle gain has been slow. Based on last week's data, what should I change?"),
    ]

    from rich.console import Console
    from rich.markdown import Markdown


    def run_with_clarification(graph, user_id, case_label, case_query):
        print(f"\n{'=' * 60}")
        print(f"  {case_label}")
        print(f"  Query: {case_query}")
        print('=' * 60)
        result = graph.run(user_id, case_query)
        while result["type"] == "clarification":
            # answers_map: {interrupt_id: {question_id: answer}}
            answers_map = {}
            for intr in result["interrupts"]:
                per_question_answers = {}
                # Options/questions may be Pydantic objects or plain dicts after checkpoint serialization
                for q in intr["questions"]:
                    q_id = q.id if hasattr(q, "id") else q["id"]
                    q_text = q.question if hasattr(q, "question") else q["question"]
                    options = q.options if hasattr(q, "options") else q["options"]
                    print(f"\n[Q] {q_text}")
                    for i, opt in enumerate(options, 1):
                        label_text = opt.label if hasattr(opt, "label") else opt["label"]
                        print(f"  {i}. {label_text}")
                    print(f"  {len(options) + 1}. Other (free text)")

                    choice = input("Enter choice number: ").strip()
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(options):
                            opt = options[idx]
                            answer = opt.id if hasattr(opt, "id") else opt["id"]
                        else:
                            answer = input("Enter free text: ").strip()
                    except ValueError:
                        answer = choice
                    per_question_answers[q_text] = answer
                answers_map[intr["id"]] = per_question_answers
            result = graph.resume(thread_id=result["thread_id"], answers=answers_map)
        print(result["content"])
        # Console().print(Markdown(result["content"]))

    try:
        for case_label, case_query in test_cases:
            run_with_clarification(g, user.id, case_label, case_query)

    finally:
        # --- 3. Clean up ---
        sql.delete_user(user.id)
        g.close()
        engine.dispose()
        print("\nTest user cleaned up.")
