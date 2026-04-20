import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from api.dependencies import get_graph
from api.routes.chat import router as chat_router
from api.routes.users import router as users_router
from api.routes.records import router as records_router


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — warming up Graph (DB connections)...")
    graph = get_graph()
    logger.info("Graph ready.")
    yield
    logger.info("Shutting down — closing Graph resources...")
    graph.close()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="HealthAgent API",
    description="Personal health assistant powered by a multi-agent LangGraph pipeline.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(chat_router)
app.include_router(users_router)
app.include_router(records_router)


@app.get("/health", tags=["meta"])
def health_check():
    """Liveness probe — returns 200 OK if the server is up."""
    return {"status": "ok"}
