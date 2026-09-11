from fastapi import APIRouter

from terrasentry_api.routers import batch, dds, health, mock_sap, runs, suppliers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(suppliers.router)
api_router.include_router(runs.router)
api_router.include_router(batch.router)
api_router.include_router(dds.router)
api_router.include_router(mock_sap.router)

__all__ = ["api_router"]
