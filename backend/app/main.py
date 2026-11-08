"""Application factory. Run with `uvicorn app.main:app --reload` from the backend folder."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import sessionmaker

from app.accounts import seed_accounts, warn_about_default_password
from app.activity import prune_activity
from app.catalog import Catalog
from app.config import Settings
from app.db import Base, add_missing_columns, make_engine
from app.limits import BodySizeLimit
from app.rag.runtime import AgentHolder
from app.reports import new_signing_key
from app.routers import admin, auth, catalog, chat, demo, medicines, my, scan, toxicity, users
from app.scanner import ScannerHolder
from app.toxicity import ToxHolder

DESCRIPTION = (
    "Pill identification and interaction checks for the Tujya project. "
    "Information uniquement, consultez un pharmacien ou un médecin. "
    "No doses are ever given; a pair missing from the database is reported as "
    '"aucune interaction connue dans cette base de données", never as safe.'
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    # Medicine tables: their own database (PostgreSQL in docker compose), read only here.
    pharma_engine = make_engine(settings.pharma_database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(engine)
        add_missing_columns(engine, Base.metadata)  # e.g. phone, photo on an older database
        with session_factory() as db:
            seed_accounts(db, settings)
            warn_about_default_password(db, settings)
            prune_activity(db, settings.activity_retention_days)
        # Module 2: load the chunk index and both Ollama models in the background, so the
        # first question does not wait for them (D78). The API answers meanwhile.
        warm_up = None
        if settings.rag_warmup:

            async def run_warm_up() -> None:
                report = await app.state.agents.warm_up()
                logging.getLogger("tujya").warning("agent warm-up: %s", report)

            warm_up = asyncio.create_task(run_warm_up())
        yield
        if warm_up is not None:
            warm_up.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await warm_up
        engine.dispose()
        pharma_engine.dispose()

    # Swagger UI at /docs (required by the course); the older /api/docs address redirects
    # there and /api/openapi.json serves the same schema, so existing links keep working.
    app = FastAPI(
        title="Tujya API",
        version="0.2.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    @app.get("/api/docs", include_in_schema=False)
    def old_docs_address() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/api/openapi.json", include_in_schema=False)
    def old_schema_address() -> JSONResponse:
        return JSONResponse(app.openapi())

    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.answer_key = new_signing_key(settings.answer_signing_key)
    app.state.catalog = Catalog(settings.processed_dir)
    app.state.pharma_engine = pharma_engine
    app.state.scanner = ScannerHolder(
        settings.models_dir,
        providers=settings.onnx_providers,
        threads=settings.onnx_threads,
        conf=settings.scan_detection_confidence,
    )
    # Bonus: Tox21 toxicity model, loaded on first use (models/tox21, docs/TOXICITY.md).
    app.state.toxicity = ToxHolder(settings.tox_model_dir, settings.ingredient_smiles_file)
    # Module 2 agent: built on the first /api/chat call (Ollama, chunk index in ChromaDB).
    app.state.agents = AgentHolder(
        settings, pharma_engine, app.state.scanner, toxicity=app.state.toxicity
    )
    # Refuse an oversized upload from its Content-Length, before the body is read.
    app.add_middleware(BodySizeLimit, max_bytes=settings.scan_max_bytes + 64 * 1024)

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(admin.router)
    app.include_router(catalog.router)
    app.include_router(catalog.public_router)
    app.include_router(scan.router)
    app.include_router(medicines.router)
    app.include_router(demo.router)
    app.include_router(chat.router)
    app.include_router(toxicity.router)
    app.include_router(my.router)
    app.include_router(my.public_router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
