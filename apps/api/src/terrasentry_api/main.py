"""FastAPI application factory: lifespan services, CORS, routers, and error mapping."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from terrasentry_core.errors import (
    InvalidReviewDecisionError,
    InvalidTransitionError,
    SeedLookupError,
)

from terrasentry_api.config import settings
from terrasentry_api.routers import api_router
from terrasentry_api.services import ServicesFactory, build_services


def create_app(services_factory: ServicesFactory = build_services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with services_factory() as services:
            app.state.services = services
            try:
                yield
            finally:
                del app.state.services

    app = FastAPI(title="TerraSentry API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(SeedLookupError)
    async def _not_found(_: Request, exc: SeedLookupError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(InvalidReviewDecisionError)
    async def _conflict(_: Request, exc: InvalidReviewDecisionError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidTransitionError)
    async def _invalid_transition(_: Request, exc: InvalidTransitionError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(api_router)
    return app


app = create_app()
