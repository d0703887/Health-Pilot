import uuid
import datetime
import logging
from typing import List, Literal

from langchain_openai import ChatOpenAI
from langchain.messages import SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SIMILARITY_DISTANCE_THRESHOLD = 0.15  # cosine distance (lower = more similar)
EPISODIC_TTL_DAYS = 14


class ExtractedInsight(BaseModel):
    content: str = Field(description="A concise, self-contained fact about the user.")
    memory_type: Literal["semantic", "procedural", "episodic"] = Field(
        description=(
            "semantic: stable preferences or facts. "
            "procedural: behavioral patterns or habits. "
            "episodic: temporary health events or experiences."
        )
    )


class ExtractionResult(BaseModel):
    insights: List[ExtractedInsight] = Field(default_factory=list)


EXTRACTION_PROMPT = """\
You are analyzing a recent conversation between a user and their personal health assistant.
Your job: extract only insights worth storing as long-term memory about the user.

EXTRACT:
- Preferences (e.g. "prefers morning workouts", "dislikes cardio")
- Behavioral patterns (e.g. "tends to skip breakfast on busy days")
- Personal constraints (e.g. "vegetarian", "no gym access", "recovering from knee injury")
- Temporary health context (e.g. "feeling low energy this week", "knee has been bothering them")

DO NOT EXTRACT:
- Specific logged events with numbers (meal/workout/sleep logs — these go to SQL)
- Generic advice given by the assistant
- Greetings, small talk, or one-word replies
- Anything speculative or uncertain

Classify each insight:
- semantic: stable facts/preferences unlikely to change soon
- procedural: recurring behavioral patterns or habits
- episodic: specific temporary events or health states (expires in ~2 weeks)

Return an empty list if there is nothing worth storing.

Conversation:
{conversation}
"""


class MemoryExtractor:
    def __init__(self, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.1,
            api_key=openai_api_key,
        ).with_structured_output(ExtractionResult)

    def extract_and_store(self, user_id: str, messages: List[dict], memory_manager) -> int:
        """
        Analyzes a list of conversation messages and stores relevant insights in ChromaDB.
        Deduplicates against existing memories by cosine similarity before inserting.
        Returns the number of insights stored.
        """
        if not messages:
            return 0

        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in messages
        )
        prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

        try:
            result: ExtractionResult = self.llm.invoke([SystemMessage(content=prompt)])
        except Exception:
            logger.exception("Memory extraction LLM call failed for user %s", user_id)
            return 0

        if not result.insights:
            return 0

        stored = 0
        for insight in result.insights:
            try:
                self._store_with_deduplication(user_id, insight, memory_manager)
                stored += 1
            except Exception:
                logger.exception("Failed to store insight for user %s: %s", user_id, insight.content)

        logger.info("Memory extraction: stored %d/%d insights for user %s", stored, len(result.insights), user_id)
        return stored

    def _store_with_deduplication(self, user_id: str, insight: ExtractedInsight, memory_manager) -> None:
        """
        Queries ChromaDB for a similar existing memory of the same type.
        If one is found within the similarity threshold, deletes it before inserting
        the newer version (latest-wins). Otherwise inserts directly.
        """
        chroma = memory_manager.chroma

        similar = chroma.collection.query(
            query_texts=[insight.content],
            n_results=1,
            where={
                "$and": [
                    {"user_id": user_id},
                    {"memory_type": insight.memory_type},
                ]
            },
            include=["distances"],
        )

        if similar["ids"] and similar["ids"][0]:
            distance = similar["distances"][0][0]
            if distance < SIMILARITY_DISTANCE_THRESHOLD:
                old_id = similar["ids"][0][0]
                chroma.delete_memory(old_id)

        metadata = {
            "user_id": user_id,
            "memory_type": insight.memory_type,
            "source": "reflection",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if insight.memory_type == "episodic":
            expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=EPISODIC_TTL_DAYS)
            metadata["expires_at"] = expires_at.isoformat()

        chroma.collection.add(
            ids=[str(uuid.uuid4())],
            documents=[insight.content],
            metadatas=[metadata],
        )