from memory import RedisManager, SQLManager, ChromaManager
from core.config import settings

import datetime
from typing import Dict, Any, List, Literal, Optional
import redis
import sqlalchemy
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction


class UnifiedMemoryManager:
    """
    A unified interface providing memory tools for the Health Agent.
    Aggregates Redis (Short-term), PostgreSQL (Structured Long-term),
    and ChromaDB (Unstructured Long-term).
    """

    def __init__(
            self,
            redis_client: redis.Redis,
            ttl_hours: int,
            sql_engine: sqlalchemy.Engine,
            openai_ef: OpenAIEmbeddingFunction,
            chroma_client: chromadb.ClientAPI,
    ):
        self.redis = RedisManager(redis_client, ttl_hours)
        self.sql = SQLManager(sql_engine)
        self.chroma = ChromaManager(openai_ef, chroma_client)

    # ==========================================
    # SQL TOOLS (Structured Data)
    # ==========================================

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the user's profile and active goals from SQL.
        Returns None if the user does not exist.
        """
        return self.sql.get_user_profile_state(user_id)

    def get_recent_health_snapshot(self, user_id: str, days: int = 7) -> str:
        """
        Retrieves a compact table-formatted snapshot of the user's nutrition, workouts,
        and sleep over the last X days.
        """
        end_datetime = datetime.datetime.now(datetime.timezone.utc)
        start_datetime = end_datetime - datetime.timedelta(days=days)
        end_date = end_datetime.date()
        start_date = start_datetime.date()

        nutrition_records = self.sql.get_nutrition_in_range(user_id, start_datetime, end_datetime)
        workout_records = self.sql.get_workout_in_range(user_id, start_datetime, end_datetime)
        sleep_records = self.sql.get_sleep_data_in_range(user_id, start_date, end_date)

        def _table(headers: list, rows: list) -> str:
            lines = [" | ".join(headers)]
            for row in rows:
                lines.append(" | ".join(str(v) if v is not None else "-" for v in row))
            return "\n".join(lines)

        def _ts(val) -> str:
            """Truncate datetime to YYYY-MM-DD HH:MM."""
            s = str(val)
            return s[:16] if len(s) >= 16 else s

        nutrition_table = _table(
            ["date", "meal", "food", "kcal", "pro", "carb", "fat"],
            [(_ts(n.timestamp), n.meal_type, n.food_name,
              n.calories, n.protein_g, n.carbs_g, n.fats_g)
             for n in nutrition_records]
        ) if nutrition_records else "No records."

        workout_table = _table(
            ["date", "activity", "min", "intensity", "notes"],
            [(_ts(w.timestamp), w.activity_type, w.duration_minutes,
              w.intensity, w.notes)
             for w in workout_records]
        ) if workout_records else "No records."

        sleep_table = _table(
            ["date", "hrs", "quality"],
            [(s.date, s.duration_hours, s.quality_score)
             for s in sleep_records]
        ) if sleep_records else "No records."

        return (
            f"=== Health Snapshot (last {days} days) ===\n\n"
            f"--- Nutrition ---\n{nutrition_table}\n\n"
            f"--- Workouts ---\n{workout_table}\n\n"
            f"--- Sleep ---\n{sleep_table}"
        )

    def log_entry(self, user_id: str, entry_type: Literal["nutrition", "workout", "sleep", "goal"], **kwargs) -> Any:
        """
        A unified routing tool to log a new entry to the appropriate SQL table.
        The agent passes the entry_type and the required kwargs.
        """
        if entry_type == "nutrition":
            # Expected kwargs: food_name, calories, protein_g, carbs_g, fats_g, timestamp (optional), meal_type (optional)
            timestamp = kwargs.get("timestamp", datetime.datetime.now(datetime.timezone.utc))
            return self.sql.create_nutrition(
                user_id=user_id,
                timestamp=timestamp,
                food_name=kwargs["food_name"],
                calories=kwargs["calories"],
                protein_g=kwargs["protein_g"],
                carbs_g=kwargs["carbs_g"],
                fats_g=kwargs["fats_g"],
                meal_type=kwargs.get("meal_type")
            )

        elif entry_type == "workout":
            # Expected kwargs: activity_type, duration_minutes, timestamp (optional), intensity (optional), notes (optional)
            timestamp = kwargs.get("timestamp", datetime.datetime.now(datetime.timezone.utc))
            return self.sql.create_workout(
                user_id=user_id,
                timestamp=timestamp,
                activity_type=kwargs["activity_type"],
                duration_minutes=kwargs["duration_minutes"],
                intensity=kwargs.get("intensity"),
                notes=kwargs.get("notes")
            )

        elif entry_type == "sleep":
            # Expected kwargs: duration_hours, date (optional), quality_score (optional), sleep_stages_json (optional)
            date_val = kwargs.get("date", datetime.datetime.now(datetime.timezone.utc).date())
            return self.sql.create_sleep_data(
                user_id=user_id,
                date=date_val,
                duration_hours=kwargs["duration_hours"],
                quality_score=kwargs.get("quality_score"),
                sleep_stages_json=kwargs.get("sleep_stages_json")
            )

        elif entry_type == "goal":
            # Expected kwargs: goal_type, description, target_date (optional)
            return self.sql.create_goal(
                user_id=user_id,
                goal_type=kwargs["goal_type"],
                description=kwargs["description"],
                target_date=kwargs.get("target_date")
            )
        else:
            raise ValueError(f"Unsupported entry_type: {entry_type}")

    # ==========================================
    # CHROMA TOOLS (Unstructured Data)
    # ==========================================

    def memorize_user_fact(self, user_id: str, memory_type: Literal["semantic", "procedural", "episodic"],
                           fact: str) -> str:
        """
        Saves an unstructured observation about the user (e.g., "Prefers morning workouts", "Injured left knee").
        """
        return self.chroma.add_memory(user_id=user_id, memory_type=memory_type, content=fact, source="agent_direct")

    def recall_context(self, user_id: str, query: str, memory_type: str = None) -> List[Dict[str, Any]]:
        """
        Searches the user's semantic history for relevance to the current conversation.
        """
        return self.chroma.search_memory(user_id=user_id, query=query, memory_type=memory_type)

    def forget_outdated_fact(self, memory_id: str) -> str:
        """
        Deletes a specific memory from Chroma if the user states their preferences or constraints have changed.
        """
        self.chroma.delete_memory(memory_id)
        return f"Memory {memory_id} successfully deleted."

    # ==========================================
    # REDIS TOOLS (Short-term Context)
    # ==========================================

    def add_to_conversation_history(self, user_id: str, role: str, content: str) -> None:
        """
        Appends a message to the user's short-term conversation history in Redis.
        Messages older than 24 hours are automatically pruned.
        """
        self.redis.add_message(user_id=user_id, role=role, content=content)

    def get_conversation_history(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves the user's conversation history from the last 24 hours.
        Returns a list of dicts with 'role' and 'content' keys, ordered oldest-first.
        """
        return self.redis.get_history(user_id=user_id)

    def reset_conversation_context(self, user_id: str) -> str:
        """
        Wipes the 24-hour Redis history. Useful if the agent detects a complete topic change
        and wants to avoid token overflow.
        """
        self.redis.clear_context(user_id)
        return "Conversation context cleared."

    # ==========================================
    # MEMORY EXTRACTION CURSOR (Redis)
    # ==========================================

    def _cursor_key(self, user_id: str) -> str:
        return f"memory_cursor:{user_id}"

    def get_messages_since_cursor(self, user_id: str, threshold: int = 10) -> tuple[List[Dict[str, Any]], float]:
        """
        Returns (messages, last_score) for all unprocessed messages since the cursor
        if their count has reached the threshold. Returns ([], 0.0) otherwise.
        The caller must pass last_score to advance_memory_cursor after consuming the messages.
        """
        import json as _json

        cursor_score = self.redis.client.get(self._cursor_key(user_id))
        min_score = float(cursor_score) + 0.001 if cursor_score else "-inf"

        history_key = self.redis._get_history_key(user_id)
        raw_with_scores = self.redis.client.zrangebyscore(history_key, min_score, "+inf", withscores=True)

        if len(raw_with_scores) < threshold:
            return [], 0.0

        messages = [_json.loads(raw) for raw, _ in raw_with_scores]
        last_score = raw_with_scores[-1][1]
        return messages, last_score

    def advance_memory_cursor(self, user_id: str, score: float) -> None:
        """
        Advances the extraction cursor to the score of the last processed message.
        """
        self.redis.client.set(self._cursor_key(user_id), score)