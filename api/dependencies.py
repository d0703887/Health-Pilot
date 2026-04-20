from core.graph import Graph
from core.config import settings
from memory.sql.sql_manager import SQLManager

_graph: Graph | None = None


def get_graph() -> Graph:
    """
    Returns the shared Graph instance, creating it on the first call.

    FastAPI routes declare this function as a dependency via Depends(get_graph).
    FastAPI will call it automatically and pass the result into the route handler,
    so routes never need to know how the Graph is constructed.
    """
    global _graph
    if _graph is None:
        _graph = Graph(
            redis_host=settings.REDIS_HOST,
            redis_port=settings.REDIS_PORT,
            redis_db=settings.REDIS_DB,
            ttl_hours=24,
            sql_db_url=settings.SQLALCHEMY_DATABASE_URI,
            openai_api_key=settings.OPENAI_API_KEY,
            openai_model_name="text-embedding-3-small",
            chroma_host=settings.CHROMA_HOST,
            chroma_port=settings.CHROMA_PORT,
            tavily_api_key=settings.TAVILY_API_KEY,
        )
    return _graph


def get_sql() -> SQLManager:
    """Returns the SQLManager from the shared Graph instance."""
    return get_graph().memory_manager.sql
