from typing import Annotated

from fastapi import APIRouter, Depends

from terrasentry_api.schemas import HealthResponse
from terrasentry_api.services import AppServices, get_services

router = APIRouter(tags=["health"])

ServicesDep = Annotated[AppServices, Depends(get_services)]


@router.get("/health", response_model=HealthResponse)
async def health(services: ServicesDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        offline=services.offline,
        fixtures_loaded=services.fixtures_loaded,
        sap_mode=services.sap_mode,
        sap_real=services.sap_real,
    )
