from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from terrasentry_api.config import settings
from terrasentry_api.routers import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="TerraSentry API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
