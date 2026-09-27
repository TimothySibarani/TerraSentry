from fastapi import APIRouter, Depends

from terrasentry_api.auth import require_write_token
from terrasentry_api.routers import batch, dds, health, mock_sap, records, runs, suppliers

api_router = APIRouter(dependencies=[Depends(require_write_token)])
api_router.include_router(health.router)
api_router.include_router(suppliers.router)
api_router.include_router(records.router)
api_router.include_router(runs.router)
api_router.include_router(batch.router)
api_router.include_router(dds.router)
api_router.include_router(mock_sap.router)

__all__ = ["api_router"]
