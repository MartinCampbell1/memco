from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from memco.api.routes.candidates import router as candidates_router
from memco.api.routes.chat import router as chat_router
from memco.api.routes.export import router as export_router
from memco.api.routes.facts import router as facts_router
from memco.api.routes.health import router as health_router
from memco.api.routes.ingest import router as ingest_router
from memco.api.routes.persons import router as persons_router
from memco.api.routes.retrieval import router as retrieval_router
from memco.api.routes.review import router as review_router
from memco.config import load_settings
from memco.runtime import ensure_runtime

app = FastAPI(title="Memco API", version="0.1.0")
app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(persons_router)
app.include_router(export_router)
app.include_router(candidates_router)
app.include_router(facts_router)
app.include_router(retrieval_router)
app.include_router(chat_router)
app.include_router(review_router)


def serve() -> None:
    settings = load_settings()
    ensure_runtime(settings)
    uvicorn.run(
        "memco.api.app:app",
        host=os.environ.get("MEMCO_API_HOST", settings.api.host),
        port=int(os.environ.get("MEMCO_API_PORT", settings.api.port)),
        reload=False,
    )
