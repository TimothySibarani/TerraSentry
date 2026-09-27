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
        bedrock_configured=services.bedrock_configured,
        default_model=services.settings.agent_model,
        gfw_configured=services.integration.has_gfw_key,
        firms_configured=services.integration.has_firms_key,
        auth_enabled=bool(services.settings.api_token),
    )
