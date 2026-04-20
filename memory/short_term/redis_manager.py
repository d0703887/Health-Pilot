import json
import redis
from typing import List, Dict
from datetime import timedelta
import os
import time

from core.config import settings


class RedisManager:
    """
    Manages the 24-hour conversation context window for the health agent using Redis.
    Operates synchronously for local development.
    """

    def __init__(
            self,
            redis_client: redis.Redis,
            ttl_hours: int = 24,
    ):
        self.client = redis_client
        # self.client = redis.Redis(
        #     host=settings.REDIS_HOST,
        #     port=settings.REDIS_PORT,
        #     db=settings.REDIS_DB,
        #     decode_responses=True
        # )

        # Set the Time-To-Live (TTL) for 24 hours
        self.ttl = timedelta(hours=ttl_hours)

    def _get_history_key(self, user_id: str) -> str:
        return f"user:{user_id}:context:history"

    def add_message(self, user_id: str, role: str, content: str, score: float = None) -> None:
        """
        Appends a message to the user's chat history and removes messages older than 24 hours.
        score: explicit sort key (Unix timestamp). When two messages in the same turn are written
               back-to-back, the caller should pass distinct scores so that Redis sorted-set
               tie-breaking (lexicographic) never reorders them.
        """
        key = self._get_history_key(user_id)
        message = json.dumps({"role": role, "content": content})
        current_timestamp = score if score is not None else time.time()

        # Using a pipeline ensures both commands execute atomically
        pipeline = self.client.pipeline()

        # Add the new message to the sorted set with the current timestamp as the score
        pipeline.zadd(key, {message: current_timestamp})

        # Remove messages older than 24 hours
        cutoff_timestamp = current_timestamp - self.ttl.total_seconds()
        pipeline.zremrangebyscore(key, '-inf', cutoff_timestamp)

        # Expire the key itself if no new messages are added for 24 hours to clean up.
        pipeline.expire(key, self.ttl)
        pipeline.execute()

    def get_history(self, user_id: str) -> List[Dict[str, str]]:
        """
        Retrieves the conversation history for a user from the last 24 hours.
        """
        key = self._get_history_key(user_id)
        messages = self.client.zrange(key, 0, -1)
        return [json.loads(msg) for msg in messages] if messages else []

    def clear_context(self, user_id: str) -> None:
        """
        Manually clears the conversation history for a user.
        """
        self.client.delete(self._get_history_key(user_id))