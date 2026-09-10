from fastapi import APIRouter

from terrasentry_api.routers import health

api_router = APIRouter()
api_router.include_router(health.router)
