import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
import uuid
from typing import List, Dict, Any, Optional, Literal

from core.config import settings

MemorySource = Literal["onboarding", "reflection", "agent_direct", "wearable_sync"]

class ChromaManager:
    """
    Manages unstructured semantic, procedural, and episodic memory using ChromaDB.
    Connects to a ChromaDB server running via Docker.
    """

    def __init__(
            self,
            openai_ef: OpenAIEmbeddingFunction,
            chroma_client: chromadb.ClientAPI,
    ):
        # 1. Initialize the OpenAI Embedding Function
        self.openai_ef = openai_ef
        # openai_ef = OpenAIEmbeddingFunction(
        #     api_key=settings.OPENAI_API_KEY,
        #     model_name="text-embedding-3-small"
        # )

        # 2. Connect to the Dockerized Chroma server via HTTP
        self.client = chroma_client
        # self.client = chromadb.HttpClient(
        #     host=settings.CHROMA_HOST,
        #     port=settings.CHROMA_PORT
        # )

        # 3. Get or create the collection
        self.collection = self.client.get_or_create_collection(
            name="agent_long_term_memory",
            metadata={"hnsw:space": "cosine"},
            embedding_function=openai_ef
        )

    # ... (rest of the methods like add_memory and search_memory remain unchanged)

    def add_memory(self, user_id: str, memory_type: str, content: str, source: MemorySource = "reflection") -> str:
        """
        Adds a new memory to the vector database.

        :param memory_type: 'semantic', 'procedural', or 'episodic'
        :param content: The actual text to embed and store
        """
        if memory_type not in ["semantic", "procedural", "episodic"]:
            raise ValueError("memory_type must be semantic, procedural, or episodic")

        memory_id = str(uuid.uuid4())

        self.collection.add(
            ids=[memory_id],
            documents=[content],
            metadatas=[{
                "user_id": user_id,
                "memory_type": memory_type,
                "source": source
            }]
        )
        return memory_id

    def search_memory(
            self,
            user_id: str,
            query: str,
            memory_type: Optional[str] = None,
            n_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Searches the vector database for relevant context.
        """
        # Build the metadata filter
        where_filter = {"user_id": user_id}
        if memory_type:
            # If a specific type is requested, we use an AND operator
            where_filter = {
                "$and": [
                    {"user_id": user_id},
                    {"memory_type": memory_type}
                ]
            }

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter
        )

        # Format Chroma's native output into a cleaner list of dictionaries
        formatted_results = []
        if results['documents'] and results['documents'][0]:
            for doc, meta, mem_id in zip(results['documents'][0], results['metadatas'][0], results['ids'][0]):
                formatted_results.append({
                    "memory_id": mem_id,
                    "content": doc,
                    "metadata": meta
                })

        return formatted_results

    def delete_memory(self, memory_id: str) -> None:
        """Removes a specific memory if it becomes outdated or incorrect."""
        self.collection.delete(ids=[memory_id])