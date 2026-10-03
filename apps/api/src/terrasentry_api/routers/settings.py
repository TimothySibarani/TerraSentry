"""Authenticated operator configuration; accepted runs retain their own snapshot."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from terrasentry_core.countries import EU_COUNTRY_CODES, normalize_country
from terrasentry_core.seed.schemas import OperatorRecord

from terrasentry_api.services import AppServices, get_services, get_session
from terrasentry_api.store import RunStore

router = APIRouter(prefix="/settings", tags=["settings"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[AppServices, Depends(get_services)]


class OperatorUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    legal_name: str = Field(min_length=1, max_length=255)
    identifier_type: Literal["eori"] = "eori"
    identifier_value: str = Field(min_length=3, max_length=17)
    address_line: str = Field(min_length=1, max_length=255)
    postal_code: str = Field(min_length=1, max_length=32)
    city: str = Field(min_length=1, max_length=128)
    country: str
    email: str = Field(min_length=3, max_length=255)
    phone: str = Field(min_length=1, max_length=64)
    activity_type: Literal["IMPORT", "EXPORT", "DOMESTIC"] = "IMPORT"
    country_of_activity: str
    border_cross_country: str

    _countries = field_validator("country", "country_of_activity", "border_cross_country")(normalize_country)

    @field_validator("identifier_value")
    @classmethod
    def _eori(cls, value: str) -> str:
        value = value.upper()
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{1,15}", value) or value[:2] not in EU_COUNTRY_CODES:
            raise ValueError("EORI must have an EU issuing-country prefix and 1-15 letters or digits")
        return value

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("enter a valid email address")
        return value

    def profile(self) -> OperatorRecord:
        return OperatorRecord(
            operator_id="OP-CONFIGURED",
            **self.model_dump(),
            synthetic=False,
            provenance="operator_configured",
            disclosure=(
                "Operator details are configured by the operator; "
                "EORI format checked, registration not verified."
            ),
        )


class OperatorSettingOut(BaseModel):
    profile: OperatorRecord
    configured: bool
    updated_at: datetime | None = None


@router.get("/operator", response_model=OperatorSettingOut)
async def get_operator(session: SessionDep, services: ServicesDep) -> OperatorSettingOut:
    row = await RunStore(session).operator_setting()
    return OperatorSettingOut(
        profile=OperatorRecord.model_validate(row.profile) if row else services.datasets.operator,
        configured=row is not None,
        updated_at=row.updated_at if row else None,
    )


@router.put("/operator", response_model=OperatorSettingOut)
async def put_operator(payload: OperatorUpdate, session: SessionDep) -> OperatorSettingOut:
    profile = payload.profile()
    updated_at = await RunStore(session).save_operator(profile)
    await session.commit()
    return OperatorSettingOut(profile=profile, configured=True, updated_at=updated_at)
